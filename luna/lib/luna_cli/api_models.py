"""Structured read/write models behind the ``/api/luna/*`` dashboard routes.

Thin, importable (no FastAPI) so both the dashboard API and tests share one read model with
``luna_cli.tune``). Data sources are the ones the retired CLI already used:

- ``$HERMES_HOME/logs/agent.log`` — luna-ambient verdict events (tail + parse).
- ``$HERMES_HOME/luna-state.db`` — wake ledger + jev usage (``luna_core.db``).
- ``$HERMES_HOME/config.yaml`` — ``luna.ambient.thresholds`` writes (comment-preserving).
- ``luna_core.identity`` / ``luna_core.peers`` — the People surface.

Writes go through the same validated paths as the CLI: threshold writes re-parse the YAML and
roll back on failure; identity writes are the registry's explicit-manual operations.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from luna_cli import config_schema, tune


# ── Paths (same resolution as the retired `luna tune`) ──────────────────────────────────────────

def home() -> Path:
    return tune._home()


def config_path() -> Path:
    return tune.config_path()


def db_path() -> Path:
    return tune.db_path()


def agent_log() -> Path:
    return tune.agent_log()


def _sys_path() -> None:
    tune._sys_path()


# ── Verdict events ───────────────────────────────────────────────────────────────────────────────

def parse_verdict_line(line: str) -> Optional[Dict[str, Any]]:
    """One agent.log line → a structured verdict event (or None when not a verdict event)."""
    if not tune._is_verdict_event(line):
        return None
    match = tune.VERDICT_RE.search(line.rstrip())
    if not match:
        return {"kind": "raw", "raw": line.rstrip()}
    body = match.group("body")
    at_match = re.search(r"\bat=(?P<at>.+?)\s+(?:via=\S+\s+)?(?:verdict|event)=", body)
    at = at_match.group("at").strip() if at_match else ""
    reason_match = re.search(r"\breason=(?P<reason>.*?)\s+\|", body)
    fields = dict(re.findall(r"(\w+)=([^\s()]+)", body))
    quoted = {m.group("key"): m.group("val") for m in tune._QFIELD_RE.finditer(body)}
    event = fields.get("event", "")
    action = fields.get("verdict", "")
    route = fields.get("via", "")
    if event == "said":
        kind = "said"
    elif event == "settle":
        kind = "settle"
    elif event == "skip":
        kind = "skip"
    elif "jev error" in (reason_match.group("reason") if reason_match else ""):
        kind = "jev_error"
    elif action in ("reaction", "message", "silent"):
        kind = "verdict"
    else:
        kind = "other"
    # The verdict log carries ids, reasons and weights — never message or reply text
    # (PRODUCT_PLAN P5 privacy decision), so there is nothing to parse here.
    out: Dict[str, Any] = {
        "kind": kind,
        "at": at,
        "tag": match.group("tag") or "",
        "event": event,
        "action": action,
        "route": route,
        "reason": reason_match.group("reason").strip() if reason_match else "",
        "who": quoted.get("who", ""),
        "value": fields.get("value", ""),
        "addressed": fields.get("addressed", ""),
        "openq": fields.get("openq", ""),
        "fit": fields.get("fit", ""),
        "msgfit": fields.get("msgfit", ""),
        "emoji": fields.get("emoji", ""),
        "emojiconf": fields.get("emojiconf", ""),
        "wait": fields.get("wait", ""),
        "raw": line.rstrip(),
    }
    return out


def verdicts(limit: int = 50) -> List[Dict[str, Any]]:
    """Most recent verdict events from ``agent.log`` (parsed, oldest first)."""
    limit = max(1, min(int(limit), 500))
    lines = tune._read_tail(agent_log(), limit * 40)
    events = [e for e in (parse_verdict_line(ln) for ln in lines) if e]
    return events[-limit:]


def verdict_log_state() -> Dict[str, Any]:
    """Whether the verdict source exists at all (the page distinguishes 'empty' from 'missing')."""
    path = agent_log()
    return {"path": str(path), "exists": path.exists()}


# ── Wake ledger ──────────────────────────────────────────────────────────────────────────────────

def wakes(limit: int = 50) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    path = db_path()
    if not path.exists():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT kind, trigger_message_id, created_at, detail FROM wakes "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out = []
    for row in rows:
        try:
            detail = json.loads(row["detail"] or "{}")
        except ValueError:
            detail = {}
        out.append({
            "kind": row["kind"],
            "trigger_message_id": row["trigger_message_id"],
            "created_at": row["created_at"],
            "value": detail.get("value"),
            "emoji": detail.get("emoji"),
            "reason": detail.get("reason", ""),
        })
    return out


# ── Thresholds (read + comment-preserving write, shared with the Behaviour page) ───────────────

def thresholds() -> Dict[str, Any]:
    """Every cascade threshold: current value, code default, whether it is overridden, and the
    validation bounds a control needs to render safely."""
    current = tune._thresholds(tune._load_yaml(config_path()))
    defaults = tune._defaults()
    keys = sorted(set(current) | set(defaults))
    bounds = config_schema.threshold_bounds()
    return {
        "keys": keys,
        "values": {
            key: {
                "value": current.get(key, defaults.get(key)),
                "default": defaults.get(key),
                "overridden": key in current and current[key] != defaults.get(key),
                "type": type(defaults.get(key)).__name__ if key in defaults else _yaml_type(current.get(key)),
                "unknown": key not in defaults,
                **_threshold_control(key, bounds.get(key), defaults),
            }
            for key in keys
        },
        "config_path": str(config_path()),
    }


def _threshold_control(
    key: str, bound: Dict[str, Any] | None, defaults: Dict[str, Any]
) -> Dict[str, Any]:
    """Range + step + description for one threshold, or ``{}`` when nothing is known.

    Bounds come from ``config_schema.threshold_bounds()``, the same source as the generated
    ``luna.ambient.thresholds.*`` schema entries, so the slider and the config form can never
    disagree about a valid range. When the overlay lib is unavailable that is empty, and an empty
    bound means "render no slider" rather than "guess a range" — the client checks ``min`` before
    drawing one.
    """
    if not bound or bound.get("min") is None or bound.get("max") is None:
        return {}
    default = defaults.get(key)
    is_int = isinstance(default, int) and not isinstance(default, bool)
    return {
        "min": bound["min"],
        "max": bound["max"],
        "step": bound.get("step") or (1 if is_int else 0.01),
        "description": bound.get("description"),
    }


def _yaml_type(value: Any) -> str:
    return type(value).__name__ if value is not None else "float"


def _set_thresholds(values: Dict[str, Any]) -> Dict[str, Any]:
    """Write threshold overrides one key at a time (each write is validated; failures roll back).

    Unknown keys are refused; a key mapped to null is reset.
    """
    defaults = tune._defaults()
    existing = tune._thresholds(tune._load_yaml(config_path()))
    results: Dict[str, Any] = {}
    for key, value in values.items():
        if key not in defaults and key not in existing:
            results[key] = {"ok": False, "error": f"unknown threshold {key!r}"}
            continue
        if value is None:
            ok, message = tune._write_threshold(key, None)
            results[key] = {"ok": ok, "error": None if ok else message, "message": message}
            continue
        text = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        error = tune._validate_document(f"k: {text}")
        if error:
            results[key] = {"ok": False, "error": f"{value!r} is not valid YAML: {error}"}
            continue
        expected = defaults.get(key)
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            try:
                numeric = float(value) if isinstance(expected, float) else int(value)
            except (TypeError, ValueError):
                results[key] = {"ok": False, "error": f"{key} expects a number, got {value!r}"}
                continue
            if isinstance(expected, int) and isinstance(value, float) and not value.is_integer():
                results[key] = {"ok": False, "error": f"{key} expects an integer, got {value!r}"}
                continue
            text = repr(numeric) if isinstance(expected, float) else str(numeric)
        elif isinstance(expected, bool):
            if value not in (True, False, "true", "false"):
                results[key] = {"ok": False, "error": f"{key} expects true/false, got {value!r}"}
                continue
            text = "true" if value in (True, "true") else "false"
        ok, message = tune._write_threshold(key, text)
        results[key] = {"ok": ok, "error": None if ok else message, "message": message}
    return {"results": results, "state": thresholds()}


# ── Cost + health ────────────────────────────────────────────────────────────────────────────────

def cost(days: int = 0) -> Dict[str, Any]:
    """Provider-reported jev spend from the usage ledger (not a character estimate)."""
    _sys_path()
    from datetime import datetime, timedelta, timezone

    from luna_core import db as luna_db

    path = db_path()
    if not path.exists():
        return {"calls": 0, "total_usd": 0.0, "input_tokens": 0, "by_route": [], "window": _window(days)}
    since = None
    if days:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        conn = luna_db.connect(str(path), read_only=True)
    except Exception:
        return {"calls": 0, "total_usd": 0.0, "input_tokens": 0, "by_route": [], "window": _window(days)}
    try:
        spend = luna_db.jev_spend(conn, since_iso=since)
    except Exception:
        spend = {"calls": 0, "total_usd": 0.0, "input_tokens": 0, "by_route": []}
    finally:
        conn.close()
    spend["window"] = _window(days)
    return spend


def _window(days: int) -> str:
    return f"last {days} days" if days else "all time"


def health() -> Dict[str, Any]:
    """Runtime shape of the wake pipeline: paths, gateway, wake totals, jev health."""
    _sys_path()
    path = db_path()
    wake_total = None
    last_wake = None
    if path.exists():
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                wake_total = conn.execute("SELECT COUNT(*) FROM wakes").fetchone()[0]
                row = conn.execute(
                    "SELECT created_at FROM wakes ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                last_wake = row[0] if row else None
            finally:
                conn.close()
        except sqlite3.Error:
            pass
    gateway = _gateway_running()
    lines = tune._read_tail(agent_log(), 400)
    deferred = sum(1 for ln in lines if "candidate still settling" in ln)
    return {
        "home": str(home()),
        "config_path": str(config_path()),
        "config_exists": config_path().exists(),
        "db_path": str(path),
        "db_exists": path.exists(),
        "log_path": str(agent_log()),
        "log_exists": agent_log().exists(),
        "gateway_running": gateway,
        "wakes_total": wake_total,
        "last_wake_at": last_wake,
        "settled_gated_recent": deferred,
        "jev": _jev_health(),
        "memory_delivery": memory_delivery(),
    }


def _gateway_running() -> Optional[bool]:
    try:
        out = subprocess.run(["pgrep", "-af", "gateway run"], capture_output=True, text=True)
    except Exception:
        return None
    return any("gateway run" in ln for ln in out.stdout.splitlines())


def _jev_health() -> Dict[str, Any]:
    from datetime import datetime, timezone
    from luna_core import db, config_read
    from luna_core.jev import route_fingerprint, primary_overrides
    from luna_cli.onboarding import _secret
    ambient = config_read.section("luna", "ambient", default={}) or {}
    if config_read.section("luna", "setup", "jev", default="pending") != "enabled" or not ambient.get("enabled", False):
        return {"status": "off", "detail": "Optional ambient wakes are off"}
    watched = ambient.get("watched_chats") or []
    selected = config_read.section("luna", "room", "chat_id", default="")
    allowed = config_read.section("telegram", "group_allowed_chats", default=[]) or []
    raw_ambient = ((tune._load_yaml(config_path()).get("luna") or {}).get("ambient") or {})
    if ("watched_chats" in raw_ambient and not watched) or (not selected and not watched and len(allowed) != 1):
        return {"status": "pending", "detail": "Choose watched groups in Behaviour"}
    try:
        conn = db.connect(db_path(), read_only=True)
        try:
            state = json.loads(db.get_meta(conn, "ambient_health", "{}"))
        finally:
            conn.close()
        revision = route_fingerprint(ambient.get("jev") or {}, _secret, primary_overrides())
        if state.get("revision") != revision:
            return {"status": "pending", "detail": "Waiting for a check of the current Jev configuration"}
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(state["heartbeat"])).total_seconds()
        if age > max(60, float(ambient.get("poll_seconds", 3)) * 3):
            return {"status": "unknown", "detail": "Ambient worker heartbeat is stale", "last_success": state.get("last_success")}
        return state
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return {"status": "unknown", "detail": "No ambient worker heartbeat recorded"}


# ── What-if replay (offline; no messages are sent) ───────────────────────────────────────────────

def replay(limit: int = 25, recent: int = 10) -> Dict[str, Any]:
    """Recompose stored, scoped scores without any provider calls or transcript export."""
    from luna_core.jev_replay import replay as offline_replay
    from luna_core.config_read import load_config
    return offline_replay(db_path(), load_config(), limit)


# ── People (identity registry) ───────────────────────────────────────────────────────────────────

def _registry():
    _sys_path()
    from luna_core import db as luna_db
    from luna_core.identity import IdentityRegistry

    conn = luna_db.connect(str(db_path()))
    luna_db.init_db(conn)
    return conn, IdentityRegistry(conn, prefix=os.getenv("LUNA_PEER_PREFIX", "telegram_"))


def _identity_dict(ident) -> Dict[str, Any]:
    return {
        "platform": ident.platform,
        "user_id": ident.user_id,
        "peer_id": ident.peer_id,
        "display_name": ident.display_name,
        "pronouns": ident.pronouns,
        "aliases": list(ident.aliases or []),
        "role": ident.role,
        "user_id_alt": ident.user_id_alt,
        "is_manual": ident.is_manual,
        "first_seen": ident.first_seen,
        "updated_at": ident.updated_at,
    }


def identity_list(platform: Optional[str] = None) -> List[Dict[str, Any]]:
    conn, registry = _registry()
    try:
        if platform:
            idents = registry.all_for_platform(platform)
        else:
            rows = conn.execute(
                "SELECT DISTINCT platform FROM identity ORDER BY platform"
            ).fetchall()
            idents = []
            for row in rows:
                idents.extend(registry.all_for_platform(row["platform"]))
        return [_identity_dict(i) for i in idents]
    finally:
        conn.close()


def identity_upsert(platform: str, user_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Explicit manual identity facts (always wins; marked ``is_manual``)."""
    conn, registry = _registry()
    try:
        ident = registry.set_manual(
            platform,
            user_id,
            peer_id=fields.get("peer_id"),
            display_name=fields.get("display_name"),
            pronouns=fields.get("pronouns"),
            aliases=fields.get("aliases"),
            role=fields.get("role"),
            user_id_alt=fields.get("user_id_alt"),
            clear_fields={key for key, value in fields.items() if key in {"pronouns", "role", "aliases", "display_name", "user_id_alt"} and value in (None, "", [])},
        )
        from luna_core.people import refresh
        result = {"ok": True, "identity": _identity_dict(ident)}
        try:
            refresh(registry, authoritative=(ident.platform, ident.user_id))
        except (ValueError, OSError) as exc:
            result["directory_error"] = str(exc)
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def identity_merge(primary: str, alt: str, platform: Optional[str] = None) -> Dict[str, Any]:
    _sys_path()
    from luna_core import peers as luna_peers

    conn, registry = _registry()
    try:
        return luna_peers.merge_identities(
            registry,
            primary_user_id=primary,
            alt_user_id=alt,
            platform=platform,
            honcho_json_path=home() / "honcho.json",
        )
    finally:
        conn.close()


def peers_audit() -> Dict[str, Any]:
    _sys_path()
    from luna_core import peers as luna_peers

    conn, registry = _registry()
    try:
        return luna_peers.audit_identities(registry)
    finally:
        conn.close()


def peers_sync(platform: Optional[str] = None) -> Dict[str, Any]:
    _sys_path()
    from luna_core import peers as luna_peers

    conn, registry = _registry()
    try:
        return luna_peers.sync_identities(
            registry,
            platform=platform,
            honcho_json_path=home() / "honcho.json",
            honcho_store=_honcho_store(),
            room_session=_room_session(),
        )
    finally:
        conn.close()


def _honcho_store():
    from luna_core.honcho import HonchoStore

    from luna_core.honcho import connection_settings
    return HonchoStore(**connection_settings())


def _room_session() -> str:
    raw = str(os.getenv("LUNA_ROOM_SESSION_KEY") or "").strip()
    if raw:
        return raw
    try:
        data = tune._load_yaml(config_path())
    except Exception:
        return ""
    room = (data.get("luna") or {}).get("room") or {}
    chat = str(room.get("chat_id") or "").strip()
    if chat:
        return f"agent:main:telegram:group:{chat}"
    allowed = (data.get("telegram") or {}).get("group_allowed_chats")
    if isinstance(allowed, list) and len(allowed) == 1:
        return f"agent:main:telegram:group:{str(allowed[0]).strip()}"
    return ""


def memory_delivery():
    from luna_core.honcho import outbox_status
    path = db_path()
    if not path.exists():
        return {"pending": 0, "uncertain": 0, "failed": 0, "oldest_pending_at": None}
    with sqlite3.connect(path) as conn:
        return outbox_status(conn)


def set_thresholds(values):
    from luna_core import settings
    class Rejected(Exception):
        pass
    try:
        with settings.transaction():
            result = _set_thresholds(values)
            if any(not value["ok"] for value in result["results"].values()):
                raise Rejected()
    except Rejected:
        for value in result["results"].values():
            if value["ok"]:
                value.update(ok=False, error="No changes applied: another field is invalid")
        result["state"] = thresholds()
    return result
