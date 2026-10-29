"""luna-ambient — the semantic trigger and rare self-wakes.

Two ways Luna speaks unprompted:

- **Directed** — jev judges the message is addressed to Luna even without a formal Telegram mention
  (``addressed_to_luna`` high). This replaces the literal "luna" word trigger with a semantic one.
  Messages that *did* reach the gateway (formal mention / reply-to-Luna) are marked ``triggered`` by
  luna-room and are skipped here, so nothing is answered twice.
- **Ambient self-wake** — a rare, well-timed interjection, or a low-key reaction.

Dry-run is the default (``LUNA_AMBIENT_DRY_RUN=1``): intended wakes are logged, never sent.

Config (env, all optional):
  LUNA_AMBIENT_ENABLED       "true"
  LUNA_AMBIENT_DRY_RUN       "true"
  LUNA_AMBIENT_POLL          "30"
  LUNA_CHAT_ID               "" (required)
  LUNA_ROOM_SESSION_KEY      "agent:main:telegram:group:<chat>"
  LUNA_INDEX_DB              "$HERMES_HOME/luna-state.db"
  LUNA_JEV_*                 backend/model/key
  LUNA_AMBIENT_REACTIONS     "" (absent/empty = reaction tier OFF; set "👍,🤣,😭" to enable)
"""

from __future__ import annotations

from luna_core.runtime import home as runtime_home, getenv

import asyncio
import hashlib
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from luna_core import config_read  # noqa: E402
from luna_core import db as luna_db  # noqa: E402
from luna_core.cascade import (  # noqa: E402
    Candidate,
    CascadeConfig,
    Decision,
    Stage0Context,
    decide,
    is_substantive,
)
from luna_core.jev import FallbackJevClient, JevClient, resolve_jev_chain, route_tier  # noqa: E402
from luna_core.room import build_room_block, record_luna_reply  # noqa: E402
from luna_core.text import shape_group_reply, strip_media_placeholders  # noqa: E402
from luna_core.timefmt import fmt as fmt_time  # noqa: E402
from luna_core.wakes import DIRECTED, MESSAGE, REACTION, WakeBudget, WakePolicy  # noqa: E402

log = logging.getLogger("luna-ambient")

_LOCK = threading.Lock()
_NOT_SENT_LOCK = threading.Lock()
_LOGGED_NOT_SENT: Dict[str, None] = {}
_PENDING_REPLIES_LOCK = threading.Lock()
_PENDING_REPLIES: Dict[str, List[Dict[str, Any]]] = {}
# Sessions whose current turn is a self-wake (marked at pre_llm_call from our own briefs). Internal
# injected events never pass ``pre_gateway_dispatch``, so luna-room's session->surface map cannot
# see them — and the group hard limits must apply to exactly these unsolicited replies. Bounded:
# session ids accumulate for as long as the gateway lives (the mark is intentionally NOT one-shot —
# a pop let a second output of the same turn ship unshaped).
_WAKE_SESSIONS_LOCK = threading.Lock()
_WAKE_SESSIONS: Dict[str, bool] = {}
_MAP_CAP = 512
# Delivery attempts per trigger message: an unrecoverable send must not re-spend a jev batch on
# every poll forever. Bounded like the other maps.
_DELIVERY_ATTEMPTS: Dict[str, int] = {}
_DELIVERY_ATTEMPTS_MAX = 3


def _note_delivery_attempt(message_id: str) -> int:
    key = str(message_id or "")
    if not key:
        return _DELIVERY_ATTEMPTS_MAX  # unknown target: do not retry blindly
    with _WAKE_SESSIONS_LOCK:
        _DELIVERY_ATTEMPTS[key] = _DELIVERY_ATTEMPTS.get(key, 0) + 1
        while len(_DELIVERY_ATTEMPTS) > _MAP_CAP:
            _DELIVERY_ATTEMPTS.pop(next(iter(_DELIVERY_ATTEMPTS)))
        return _DELIVERY_ATTEMPTS[key]
_THREAD: Optional[threading.Thread] = None
_STOP = threading.Event()
_CTX: Any = None
_LOOP: Optional[asyncio.AbstractEventLoop] = None
# Rate-limit cooldown. When jev answers 429 with a long retry-after, every further poll would be
# another guaranteed-rejected request, which keeps the limiter pinned. Honour the server's window
# (capped, so recovery is never blocked indefinitely) and skip jev until it expires. The evaluation
# watermark is NOT advanced while paused, so no message is lost.
_JEV_PAUSE_UNTIL: float = 0.0
_JEV_PAUSE_REASON: str = ""
JEV_PAUSE_MAX_SECONDS = 600.0
# Default cooldowns when the failure carries no retry-after: payment/quota walls (HTTP 402)
# linger, everything else gets a short bounded backoff.
JEV_402_PAUSE_SECONDS = 600.0
JEV_ERROR_PAUSE_SECONDS = 60.0
# Optional paid route used only when the primary is rate-limited. Same shape as hermes'
# ``fallback_providers`` (a list of {provider, model}); add base_url/api_key_env to change hosts.
_FALLBACKS: List[Dict[str, Any]] = []

_DEFAULT_CHAT_ID = ""
# Short direct addresses use this profile's character name, never the harness brand.
def _character_name_pattern():
    from luna_core.cascade import character_identity
    name, aliases = character_identity()
    names = [re.escape(value.strip()) for value in [name, *aliases] if value.strip()]
    return re.compile(r"(?<!\w)(?:" + "|".join(names) + r")(?!\w)", re.IGNORECASE)

# meta key: timestamp of the last message sent to jev, so each message is evaluated once.
EVAL_WATERMARK_KEY = "ambient_eval_watermark"
from contextvars import ContextVar
_SCAN_TOPIC = ContextVar("ambient_topic", default="")
_SCOPE_CURSOR = 0


def _watermark_key(chat_id):
    import json
    return EVAL_WATERMARK_KEY + ":" + json.dumps([str(chat_id), _SCAN_TOPIC.get()])


def _chat_ids():
    watched = _cfg("ambient.watched_chats", None)
    if isinstance(watched, list):
        allowed = list(config_read.section("telegram", "group_allowed_chats") or [])
        legacy_room = _cfg("room.chat_id", "")
        if legacy_room:
            allowed.append(str(legacy_room))
        return list(dict.fromkeys(str(c) for c in watched if str(c) in {str(a) for a in allowed}))
    selected = _chat_id()
    return [selected] if selected else []



# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def _flag(name: str, default: bool) -> bool:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _num(name: str, default: float) -> float:
    try:
        return float(str(getenv(name, "")).strip() or default)
    except (TypeError, ValueError):
        return float(default)


def _chat_id() -> str:
    configured = str(getenv("LUNA_CHAT_ID") or _cfg("room.chat_id", _DEFAULT_CHAT_ID) or "").strip()
    if configured:
        return configured
    try:
        allowed = config_read.section("telegram", "group_allowed_chats")
        if isinstance(allowed, list) and len(allowed) == 1:
            return str(allowed[0]).strip()
    except Exception:
        pass
    return ""


def _home() -> Path:
    return runtime_home()


_LUNA_SECTION: Optional[Dict[str, Any]] = None
_LUNA_SECTION_MTIME = None


def _luna_section() -> Dict[str, Any]:
    """The ``luna:`` block from $HERMES_HOME/config.yaml (mtime-cached, so a dashboard edit takes
    effect on the next poll instead of requiring a restart). Env vars still override."""
    # The canonical loader already caches file signatures and applies the
    # active profile, managed overrides and environment interpolation.
    import copy
    result = copy.deepcopy(config_read.section("luna", default={}) or {})
    from hermes_cli.config import read_user_config_raw
    from hermes_cli import managed_scope
    explicit = ((read_user_config_raw().get("luna") or {}).get("ambient") or {})
    ambient = result.get("ambient") or {}
    if "watched_chats" not in explicit and not managed_scope.is_key_managed("luna.ambient.watched_chats"):
        ambient.pop("watched_chats", None)  # Retain the pre-selection legacy room fallback.
    raw_thresholds = explicit.get("thresholds") or {}
    if ("message_max_emotional" in raw_thresholds and "message_max_venting" not in raw_thresholds
            and not managed_scope.is_key_managed("luna.ambient.thresholds.message_max_venting")):
        (ambient.get("thresholds") or {}).pop("message_max_venting", None)
    return result


def _cfg(path: str, default: Any = None) -> Any:
    node: Any = _luna_section()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node



def _index_db_path() -> Path:
    raw = str(getenv("LUNA_INDEX_DB") or "").strip()
    return Path(os.path.expandvars(raw)).expanduser() if raw else _home() / "luna-state.db"


def _room_session_key(chat_id: str, thread_id: str = "") -> str:
    raw = str(getenv("LUNA_ROOM_SESSION_KEY") or "").strip()
    if raw:
        return raw
    from gateway.session import SessionSource, build_session_key
    from gateway.config import Platform
    from hermes_cli.profiles import get_active_profile_name
    profile = get_active_profile_name()
    if profile == "custom" and _home().parent.name != "profiles":
        profile = "default"
    return build_session_key(SessionSource(platform=Platform.TELEGRAM, chat_id=str(chat_id),
        chat_type="forum" if thread_id else "group", thread_id=str(thread_id) or None),
        profile=profile)


def _allowed_reactions() -> List[str]:
    """The reaction allow-list. Absent/empty = reaction tier OFF (plan D19: ``[]`` disables it).

    Falls back to no reactions — never to a built-in palette. A default-on tier is exactly the
    "silence is the default" inversion this gate exists to prevent.
    """
    raw = getenv("LUNA_AMBIENT_REACTIONS")
    if raw is not None:
        return [r.strip() for r in raw.split(",") if r.strip()]
    cfg = _cfg("ambient.reactions.allowed")
    if isinstance(cfg, list):
        return [str(r).strip() for r in cfg if str(r).strip()]
    return []


def _mention_fallback_patterns() -> List["re.Pattern"]:
    """Regex fallback for when jev is DOWN (error or cooldown): a text match wakes Luna anyway.

    Absent/empty = disabled (silence is the default even while jev is down). Config:
    ``luna.ambient.mention_fallback`` (list of Python regexes). Env
    ``LUNA_AMBIENT_MENTION_FALLBACK`` overrides with a single regex. This is the outage path
    only: when jev answers, its semantic "does this name Luna" judgment decides, never this regex.
    """
    raw = getenv("LUNA_AMBIENT_MENTION_FALLBACK")
    if raw is not None:
        sources = [raw.strip()] if raw.strip() else []
    else:
        cfg = _cfg("ambient.mention_fallback")
        sources = [str(p) for p in cfg] if isinstance(cfg, list) else []
    out = []
    for s in sources:
        if not s:
            continue
        try:
            out.append(re.compile(s))
        except re.error:
            log.warning("[luna-ambient] bad mention_fallback regex: %r", s)
    return out


def _regex_fallback_decision(conn: sqlite3.Connection, chat_id: str, *,
                             now: Optional[datetime] = None) -> Optional[Decision]:
    """The jev-down fallback: a message matching a configured mention regex wakes her anyway.

    This runs ONLY while jev cannot answer (hard error or cooldown). When jev is up, its semantic
    "does this name Luna" judgment decides and this regex never runs. Same dedup and
    "never double-answer" guards as :func:`_candidate`; the substantive-text gate is skipped
    because an explicit mention is substantive by definition. No patterns configured = no fallback.
    """
    # A Jev outage cannot establish a user-authored yes/no condition.
    from luna_core.behaviour_policy import validate_policy
    from luna_core.cascade import build_questions, REACTION_CRITERIA
    try:
        policy = validate_policy(_cfg("ambient.decision", {}) or {}, build_questions(list(REACTION_CRITERIA)))
    except ValueError:
        return None
    if any(rule["enabled"] and rule["action"] in ("message", "both") for rule in policy["rules"]):
        return None
    patterns = _mention_fallback_patterns()
    if not patterns:
        return None
    now = now or datetime.now(timezone.utc)
    budget = WakeBudget(conn, _wake_policy())
    ok, why = budget.can_wake(DIRECTED, now)
    if not ok:
        return None
    watermark = luna_db.get_meta(conn, _watermark_key(chat_id), "") or ""
    rows = conn.execute(
        "SELECT * FROM messages WHERE chat_id = ? AND COALESCE(thread_id, '') = ? AND is_bot = 0 AND COALESCE(triggered, 0) = 0 "
        "AND timestamp > ? ORDER BY timestamp DESC LIMIT 50",
        (chat_id, _SCAN_TOPIC.get(), watermark),
    ).fetchall()
    for row in rows:
        text = row["content"] or ""
        if not any(p.search(text) for p in patterns):
            continue
        mid = str(row["message_id"])
        if conn.execute("SELECT 1 FROM wakes WHERE trigger_message_id = ? AND chat_id = ? LIMIT 1",
                        (mid, str(chat_id))).fetchone():
            continue
        reply_to = row["reply_to_message_id"]
        if reply_to:
            target = conn.execute(
                "SELECT is_bot, peer_id FROM messages WHERE chat_id = ? AND message_id = ?",
                (str(chat_id), str(reply_to)),
            ).fetchone()
            if target and ((target["peer_id"] or "") == "luna"):
                continue
        return _attribute_candidate(Decision(
            action=MESSAGE, directed=True, value=1.0,
            reason="regex mention fallback (jev down)",
            contribution_type="directed", stage="fallback",
            chat_id=str(chat_id), target_message_id=mid,
            target_user=row["user_name"] or row["user_id"] or "",
            target_text=_display_text(text),
        ), Candidate(chat_id=chat_id, message_id=mid, text=text, timestamp=row["timestamp"]))
    return None


def _dry_run() -> bool:
    return _flag("LUNA_AMBIENT_DRY_RUN", bool(_cfg("ambient.dry_run", True)))


def _poll_seconds() -> int:
    # Responsiveness: this is the dominant reply-latency term (average = half a poll). Keep it tight;
    # jev is only called when there is a new candidate, so a fast poll spends no extra jev quota.
    return max(2, int(_num("LUNA_AMBIENT_POLL", float(_cfg("ambient.poll_seconds", 3)))))


def _cascade_config() -> CascadeConfig:
    """Build the cascade config from ``luna.ambient.thresholds`` + ``LUNA_AMBIENT_*`` env.

    Every :class:`CascadeConfig` field is wired; the dataclass defaults are the single source of
    truth for what an absent key means (they used to be hardcoded a third time here, disagreeing
    with both). Env names follow the field name (``LUNA_AMBIENT_<FIELD_UPPER>``), with the few
    historical short aliases preserved so existing deployments keep working.
    """
    base = CascadeConfig()
    aliases = {
        "reaction_yield_open_question": ("LUNA_AMBIENT_REACTION_YIELD_OPEN_Q",),
        "reaction_max_open_question": ("LUNA_AMBIENT_REACTION_MAX_OPEN_Q",),
    }
    # Old config key names that predate the CascadeConfig field names.
    config_aliases = {"message_max_venting": ("message_max_emotional",)}
    values: Dict[str, Any] = {}
    for name in base.__dataclass_fields__:
        default = getattr(base, name)
        env_names = (f"LUNA_AMBIENT_{name.upper()}",) + aliases.get(name, ())
        raw = next((getenv(e) for e in env_names if getenv(e) not in (None, "")), None)
        if raw is not None:
            parsed = _num(env_names[0], default)
            values[name] = int(parsed) if isinstance(default, int) else parsed
            continue
        cfg_names = (name,) + config_aliases.get(name, ())
        for cfg_name in cfg_names:
            cfg_val = _cfg(f"ambient.thresholds.{cfg_name}", None)
            if cfg_val is not None:
                try:
                    values[name] = int(cfg_val) if isinstance(default, int) else float(cfg_val)
                except (TypeError, ValueError):
                    pass
                break
    return replace(base, **values)


def _wake_policy() -> WakePolicy:
    """Optional hard ceilings. Default 0 / huge = no code cap; jev decides frequency."""
    from dataclasses import fields
    values = {}
    for item in fields(WakePolicy):
        raw = getenv("LUNA_AMBIENT_" + item.name.upper())
        value = raw if raw is not None else _cfg("ambient.budget." + item.name, item.default)
        if value is None and "max_per" in item.name and item.name != "emergency_max_per_hour":
            values[item.name] = None
        else:
            try:
                values[item.name] = int(value)
            except (ValueError, TypeError):
                values[item.name] = item.default
    return WakePolicy(**values)


def _jev_api_key(key_env: str) -> str:
    from luna_core.jev import profile_key
    return profile_key(key_env)


_CLIENT_CACHE = None
_CLIENT_REVISION = ""
_CLIENT_BUILT_AT = 0.0


def _jev_overrides():
    from luna_core.jev import primary_overrides
    return primary_overrides()


def _jev_client() -> JevClient:
    from luna_core.jev import build_client, route_fingerprint
    global _CLIENT_CACHE, _CLIENT_REVISION, _CLIENT_BUILT_AT, _JEV_PAUSE_UNTIL, _JEV_PAUSE_REASON
    config = _cfg("ambient.jev", {})
    overrides = _jev_overrides()
    revision = route_fingerprint(config, _jev_api_key, overrides)
    # Preserve a successful fallback for a cooldown instead of hammering the primary each scan.
    changed = revision != _CLIENT_REVISION
    previously_configured = bool(_CLIENT_REVISION)
    if _CLIENT_CACHE is None or changed or time.monotonic() - _CLIENT_BUILT_AT >= 60:
        _CLIENT_CACHE = build_client(config, _jev_api_key, overrides=overrides)
        _CLIENT_REVISION, _CLIENT_BUILT_AT = revision, time.monotonic()
        if changed and previously_configured:
            _JEV_PAUSE_UNTIL, _JEV_PAUSE_REASON = 0.0, ""
    return _CLIENT_CACHE


# --------------------------------------------------------------------------- #
# candidate scan
# --------------------------------------------------------------------------- #
def _index_conn() -> sqlite3.Connection:
    conn = luna_db.connect(_index_db_path())
    luna_db.init_db(conn)
    return conn


def _since_luna(conn: sqlite3.Connection, chat_id: str, bot_peer: str = "luna", *, now=None) -> Tuple[int, float]:
    last = conn.execute(
        "SELECT timestamp FROM messages WHERE chat_id = ? AND COALESCE(thread_id, '') = ? AND peer_id = ? "
        "ORDER BY timestamp DESC LIMIT 1",
        (chat_id, _SCAN_TOPIC.get(), bot_peer),
    ).fetchone()
    if last and last["timestamp"]:
        try:
            last_dt = datetime.fromisoformat(last["timestamp"])
        except ValueError:
            last_dt = None
        if last_dt is not None:
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            minutes = ((now or datetime.now(timezone.utc)) - last_dt).total_seconds() / 60.0
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE chat_id = ? AND COALESCE(thread_id, '') = ? AND timestamp > ? "
                "AND is_bot = 0",
                (chat_id, _SCAN_TOPIC.get(), last["timestamp"]),
            ).fetchone()["n"]
            return int(count), minutes
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE chat_id = ? AND COALESCE(thread_id, '') = ? AND is_bot = 0", (chat_id, _SCAN_TOPIC.get())
    ).fetchone()["n"]
    return int(count), 1e9


def _display_text(text: str, limit: int = 80) -> str:
    return " ".join(str(text or "").split())[:limit]


def _q(value: str, limit: int = 80) -> str:
    """Quote a value for the log so whitespace/newlines cannot break field parsing."""
    flat = " ".join(str(value or "").split())[:limit]
    return '"' + flat.replace('"', "'") + '"'


def _attribute_candidate(decision: Decision, candidate: Candidate) -> Decision:
    decision.thread_id = _SCAN_TOPIC.get()
    decision.source_timestamp = candidate.timestamp or ""
    decision.source_digest = hashlib.sha256(candidate.text.encode()).hexdigest()
    decision.source_revision = _intent_revision()
    decision.chat_id = candidate.chat_id
    decision.target_message_id = candidate.message_id
    decision.target_user = candidate.user_name or candidate.user_id or ""
    decision.target_text = _display_text(candidate.text)
    return decision


def _mark_not_sent(message_id: str) -> bool:
    key = str(message_id or "")
    if not key:
        return False
    with _NOT_SENT_LOCK:
        if key in _LOGGED_NOT_SENT:
            return False
        _LOGGED_NOT_SENT[key] = None
        while len(_LOGGED_NOT_SENT) > 4096:
            _LOGGED_NOT_SENT.pop(next(iter(_LOGGED_NOT_SENT)))
    return True


def _log_not_sent(message_id: str, reason: str, *, user: str = "", text: str = "") -> bool:
    """Record that a message was not judged. Carries ids and the reason, never the message text.

    ``text`` is accepted so callers stay unchanged; it is deliberately NOT logged (PRODUCT_PLAN
    P5): the verdict log is a local operator artifact, and writing every room message into it
    would turn a tuning surface into a transcript archive.
    """
    if not _mark_not_sent(message_id):
        return False
    clean_reason = " ".join(str(reason or "not sent to jev").split()).replace("|", "/")
    log.info(
        "[luna-ambient] [NOT-SENT] at=%s event=skip reason=%s | trig=%s who=%s",
        fmt_time(datetime.now(timezone.utc)), clean_reason, message_id, _q(user),
    )
    return True


def _log_unasked_range(conn: sqlite3.Connection, chat_id: str, *, after: str, reason: str,
                       through: Optional[str] = None, exclude_message_id: Optional[str] = None) -> int:
    clauses = ["chat_id = ?", "COALESCE(thread_id, '') = ?", "is_bot = 0", "timestamp > ?"]
    params: List[Any] = [chat_id, _SCAN_TOPIC.get(), after]
    if through is not None:
        clauses.append("timestamp <= ?")
        params.append(through)
    if exclude_message_id is not None:
        clauses.append("message_id != ?")
        params.append(str(exclude_message_id))
    rows = conn.execute(
        f"SELECT message_id, user_name, user_id, content FROM messages WHERE {' AND '.join(clauses)} "
        "ORDER BY timestamp, message_id",
        params,
    ).fetchall()
    for row in rows:
        _log_not_sent(
            str(row["message_id"]), reason,
            user=row["user_name"] or row["user_id"] or "",
            text=row["content"] or "",
        )
    return len(rows)


def _log_triggered_messages(conn: sqlite3.Connection, chat_id: str, *, after: str) -> int:
    rows = conn.execute(
        "SELECT message_id, user_name, user_id, content FROM messages "
        "WHERE chat_id = ? AND COALESCE(thread_id, '') = ? AND is_bot = 0 AND COALESCE(triggered, 0) = 1 AND timestamp > ? "
        "ORDER BY timestamp, message_id",
        (chat_id, _SCAN_TOPIC.get(), after),
    ).fetchall()
    for row in rows:
        _log_not_sent(
            str(row["message_id"]), "handled reactively",
            user=row["user_name"] or row["user_id"] or "",
            text=row["content"] or "",
        )
    return len(rows)


def _candidate(conn: sqlite3.Connection, chat_id: str) -> Optional[Candidate]:
    """Newest not-yet-evaluated message, so a directed message is answered promptly.

    Newest-first (not oldest) matters: with a backlog, oldest-first made Luna reply minutes late.
    Older un-evaluated messages are skipped when the watermark advances past them.
    """
    min_chars = _cascade_config().min_candidate_chars
    name_pattern = _character_name_pattern()
    watermark = luna_db.get_meta(conn, _watermark_key(chat_id), "") or ""
    rows = conn.execute(
        "SELECT * FROM messages WHERE chat_id = ? AND COALESCE(thread_id, '') = ? AND is_bot = 0 AND COALESCE(triggered, 0) = 0 "
        "AND timestamp > ? ORDER BY timestamp DESC LIMIT 50",
        (chat_id, _SCAN_TOPIC.get(), watermark),
    ).fetchall()
    for row in rows:
        # Defensive: rows indexed before the parser stripped media placeholders still carry a
        # ``/.luna/cache/…`` path that would match the name regex and wake her on a meme.
        text = strip_media_placeholders(row["content"] or "")
        user = row["user_name"] or row["user_id"] or ""
        if not is_substantive(text, min_chars=min_chars) and not name_pattern.search(text):
            _log_not_sent(str(row["message_id"]), "not substantive", user=user, text=text)
            continue
        # Dedup: never act on the same message twice (prevents re-acting every poll). Scoped by
        # chat — Telegram message ids repeat across chats.
        if conn.execute("SELECT 1 FROM wakes WHERE trigger_message_id = ? AND chat_id = ? LIMIT 1",
                        (str(row["message_id"]), str(chat_id))).fetchone():
            _log_not_sent(str(row["message_id"]), "already woken", user=user, text=text)
            continue
        if conn.execute("SELECT 1 FROM ambient_intents WHERE chat_id=? AND message_id=? LIMIT 1",
                        (str(chat_id), str(row["message_id"]))).fetchone():
            continue  # A receipt, including silence/failure, never buys another judgment.
        # Never double-answer: skip replies to Luna's own messages (those trigger her reactively).
        reply_to = row["reply_to_message_id"]
        if reply_to:
            target = conn.execute(
                "SELECT is_bot, peer_id FROM messages WHERE chat_id = ? AND message_id = ?",
                (str(chat_id), str(reply_to)),
            ).fetchone()
            if target and ((target["peer_id"] or "") == "luna"):
                _log_not_sent(str(row["message_id"]), "reply to companion", user=user, text=text)
                continue
        return Candidate(
            chat_id=chat_id,
            message_id=str(row["message_id"]),
            text=text,
            user_id=row["user_id"],
            user_name=row["user_name"],
            timestamp=row["timestamp"],
            is_bot=bool(row["is_bot"]),
            reply_to_message_id=row["reply_to_message_id"],
        )
    return None


def _recent_pairs(conn: sqlite3.Connection, chat_id: str, limit: int) -> List[Tuple[str, str, Optional[str]]]:
    """Recent messages with reply edges preserved: ``(from, text, reply_to_name|None)``."""
    rows = conn.execute(
        "SELECT user_name, content, reply_to_message_id FROM messages WHERE chat_id = ? AND COALESCE(thread_id, '') = ? "
        "ORDER BY timestamp DESC LIMIT ?",
        (chat_id, _SCAN_TOPIC.get(), limit),
    ).fetchall()
    out: List[Tuple[str, str, Optional[str]]] = []
    for row in reversed(rows):
        reply_to = row["reply_to_message_id"]
        reply_name: Optional[str] = None
        if reply_to:
            target = conn.execute(
                "SELECT user_name, peer_id, is_bot FROM messages WHERE chat_id = ? AND message_id = ? AND COALESCE(thread_id, '') = ?",
                (str(chat_id), str(reply_to), _SCAN_TOPIC.get()),
            ).fetchone()
            if target is not None:
                if (target["peer_id"] or "") == "luna":
                    from luna_core.cascade import character_identity
                    reply_name = character_identity()[0]
                else:
                    reply_name = target["user_name"] or "someone"
        out.append((row["user_name"] or "someone", row["content"] or "", reply_name))
    return out


def _luna_recent_activity(conn: sqlite3.Connection, chat_id: str, now: datetime) -> str:
    """Human-readable summary of Luna's recent wakes, so jev can judge freshness.

    All time arithmetic happens here in code (jev cannot compare dates reliably).
    """
    import json as _json

    def _age_minutes(ts: Optional[str]) -> Optional[float]:
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds() / 60.0

    rows = conn.execute(
        "SELECT kind, detail, created_at FROM wakes WHERE chat_id = ? ORDER BY created_at DESC LIMIT 20",
        (chat_id,),
    ).fetchall()
    reactions = [r for r in rows if r["kind"] == REACTION]
    day_count = sum(1 for r in reactions if (_age_minutes(r["created_at"]) or 1e9) <= 1440)

    last = reactions[0] if reactions else None
    last_age = _age_minutes(last["created_at"]) if last else None
    last_emoji = None
    if last:
        try:
            last_emoji = (_json.loads(last["detail"] or "{}") or {}).get("emoji")
        except ValueError:
            last_emoji = None

    from luna_core.cascade import character_identity
    name, _ = character_identity()
    parts = [f"{name} has reacted {day_count} time(s) in the last 24 hours."]
    if last_age is None:
        parts.append(f"{name} has not reacted recently, so a reaction would feel fresh rather than repetitive.")
    else:
        tail = f" ({last_emoji})" if last_emoji else ""
        cooldown = _wake_policy().reaction_cooldown_minutes
        if not cooldown:
            parts.append(f"The last reaction was {int(last_age)} minutes ago{tail}.")
        elif last_age >= cooldown:
            parts.append(
                f"The last reaction was {int(last_age)} minutes ago{tail}. {name}'s rule is at most one "
                f"reaction every {cooldown} minutes, and that window has already passed, so a reaction "
                "now would not feel repetitive."
            )
        else:
            parts.append(
                f"The last reaction was {int(last_age)} minutes ago{tail}. {name}'s rule is at most one "
                f"reaction every {cooldown} minutes, so reacting again this soon would feel repetitive."
            )
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# evaluate + wake
# --------------------------------------------------------------------------- #
def _init_watermark(conn: sqlite3.Connection, chat_id: str, *, now: Optional[datetime] = None) -> None:
    """On first run, start from the newest message so we don't grind through all history.

    Without this the poller evaluates the oldest un-evaluated message first (one per poll), so a
    fresh index would spend hours catching up to "now" instead of watching live messages.
    """
    if luna_db.get_meta(conn, _watermark_key(chat_id), ""):
        return
    row = conn.execute(
        "SELECT MAX(timestamp) AS ts FROM messages WHERE chat_id = ? AND COALESCE(thread_id, '') = ?", (str(chat_id), _SCAN_TOPIC.get())
    ).fetchone()
    ts = (row["ts"] if row else None) or (now or datetime.now(timezone.utc)).isoformat()
    luna_db.set_meta(conn, _watermark_key(chat_id), ts)
    log.info("[luna-ambient] initialized eval watermark at %s", ts)


def _fast_forward_if_stale(conn: sqlite3.Connection, chat_id: str, *, now: datetime) -> None:
    """Skip a stale backlog instead of grinding through it (and spending jev calls on old messages).

    If the watermark lags more than ``ambient.stale_after_minutes`` behind, jump it to the newest
    message. Old messages never need a reaction/directed reply anyway.
    """
    stale_minutes = float(getenv("LUNA_AMBIENT_STALE_AFTER_MINUTES",
                                    _cfg("ambient.stale_after_minutes", 15)))
    watermark = luna_db.get_meta(conn, _watermark_key(chat_id), "") or ""
    if not watermark:
        return
    cutoff = (now - timedelta(minutes=stale_minutes)).isoformat()
    if watermark >= cutoff:
        return
    newest = conn.execute(
        "SELECT MAX(timestamp) AS ts FROM messages WHERE chat_id = ? AND COALESCE(thread_id, '') = ?", (str(chat_id), _SCAN_TOPIC.get())
    ).fetchone()
    ts = newest["ts"] if newest else None
    if ts and ts > watermark:
        _log_unasked_range(
            conn, chat_id, after=watermark, through=ts, reason="stale backlog",
        )
        luna_db.set_meta(conn, _watermark_key(chat_id), ts)
        log.info("[luna-ambient] watermark stale (>%sm); fast-forwarded to %s", stale_minutes, ts)


def evaluate(conn: sqlite3.Connection, chat_id: str, *, now: Optional[datetime] = None,
             dry_run: bool = True, client: Optional[JevClient] = None) -> Decision:
    """Run stages 0–3 for one scan. Returns the Decision.

    Does NOT record the wake: the caller records it only AFTER delivery succeeds (``_record_wake``).
    Recording here would make ``_candidate`` skip the message on a failed delivery, so the watermark
    rollback in ``poll_once`` could never retry it.
    """
    now = now or datetime.now(timezone.utc)
    source_revision = _intent_revision()
    _init_watermark(conn, chat_id, now=now)
    _fast_forward_if_stale(conn, chat_id, now=now)
    watermark = luna_db.get_meta(conn, _watermark_key(chat_id), "") or ""
    _log_triggered_messages(conn, chat_id, after=watermark)
    cand = _candidate(conn, chat_id)
    if cand is None:
        return Decision(action="silent", reason="no candidate", stage="scan")

    # Cost gate: in a busy room most messages are superseded within seconds, so paying jev for each
    # one is mostly waste. Let a candidate *settle* first, but never gate anything that names Luna —
    # a message addressed to her must be judged immediately or she misses it. The watermark is left
    # untouched here, so a skipped message is reconsidered (and only skipped) on a later scan.
    settle = _settle_seconds()
    if settle > 0 and not _character_name_pattern().search(cand.text or ""):
        age = settle
        if cand.timestamp:
            try:
                stamp = datetime.fromisoformat(str(cand.timestamp))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                age = (now - stamp).total_seconds()
            except ValueError:
                pass
        if age < settle:
            decision = _attribute_candidate(
                Decision(action="silent", reason="candidate still settling", stage="scan"), cand
            )
            decision.scores["settle_wait_seconds"] = max(0.0, settle - age)
            return decision

    new_count, minutes = _since_luna(conn, chat_id, now=now)
    ctx = Stage0Context(new_messages_since_luna=new_count, minutes_since_luna=minutes)
    budget = WakeBudget(conn, _wake_policy())
    allowed = _allowed_reactions()

    try:
        client = client or _jev_client()
    except Exception:
        _health(conn, "down", "Jev route configuration is invalid; review Behaviour")
        return _attribute_candidate(Decision(action="silent", stage="config", reason="invalid Jev route configuration"), cand)
    from luna_core.judgement_guard import reserve
    operation = getattr(client, "operation", None)
    def reserve_attempt():
        return reserve(conn, datetime.now(timezone.utc), calls_per_hour=int(_cfg("ambient.guard.max_jev_calls_per_hour", 60)),
                       cost_per_day=float(_cfg("ambient.guard.max_reported_cost_per_day", 1.0)))
    if operation is not None:
        client.validated = False
        client.last_answers = None
        operation.guard = reserve_attempt
        operation.observer = lambda serving, usage: luna_db.record_jev_usage(
            conn, route=route_tier({"model": serving.model, "base_url": serving.base_url}),
            usage=usage, requested_model=serving.model, trigger_message_id=cand.message_id)
    decision = decide(
        client,
        candidate=cand,
        ctx=ctx,
        recent=_recent_pairs(conn, chat_id, 30),
        config=_cascade_config(),
        budget=budget,
        now=now,
        reactions_enabled=bool(allowed),
        allowed_reactions=allowed,
        decision_policy=_cfg("ambient.decision", {}),
        reaction_criteria=_cfg("ambient.reactions.criteria", {}),
        room_register=_cfg("ambient.room_register"),
        before_jev=None if operation is not None else reserve_attempt,
        extra_state={"luna_recent_activity": _luna_recent_activity(conn, chat_id, now)},
    )

    # Advance the evaluation watermark so we never re-ask jev about the same message. Do NOT
    # advance on a jev error (e.g. 429) so the message is retried on a later scan.
    jev_failed = decision.stage == "stage1" and "jev error" in decision.reason
    decision.jev_route = _jev_route_label(client)
    _attribute_candidate(decision, cand)
    decision.source_revision = source_revision
    if jev_failed:
        # decide() failed closed only after the whole chain raised — a fallback that is actually
        # serving returns answers and never lands here. So honour the server's retry window now
        # regardless of which route raised, instead of re-hammering an exhausted chain every poll.
        # Capped, so a bogus/oversized window cannot disable Luna permanently.
        # Advanced past the primary = the whole fallback side died with it.
        if getattr(client, "_index", 0):
            log.info("[luna-ambient] jev fallback chain exhausted (%s)",
                     getattr(client, "served_by", "fallback"))
        match = re.search(r"retry-after\s+(\d+(?:\.\d+)?)s", decision.reason)
        if match and float(match.group(1)) > 1.0:
            _pause_jev(float(match.group(1)), decision.reason.split(":")[0].strip())
        elif re.search(r"HTTP 402|payment|insufficient|out of (funds|credits|quota)",
                       decision.reason, re.IGNORECASE):
            # A payment/quota wall does not clear in seconds and sends no retry-after. Without a
            # pause every poll re-asks the same message forever (the 402 storm). Long cooldown;
            # messages keep indexing and are evaluated once the wall clears.
            _pause_jev(JEV_402_PAUSE_SECONDS, "payment/quota wall (HTTP 402)")
        else:
            # Any other fail-closed (transport blip, 5xx, malformed answer) gets a short backoff
            # too — a persistent failure must not re-spend a request batch every poll.
            _pause_jev(JEV_ERROR_PAUSE_SECONDS, decision.reason.split(":")[0].strip())
        # jev is down: the configured mention regex is the only thing that still wakes her.
        # The watermark stays put either way (retried when jev returns); the wake's own dedup
        # (wakes.trigger_message_id) keeps the fallback from re-firing on the same message.
        fallback = _regex_fallback_decision(conn, chat_id, now=now)
        if fallback is not None:
            fallback.jev_route = decision.jev_route
            fallback.source_revision = source_revision
            decision = fallback
    if not jev_failed and cand.timestamp:
        _log_unasked_range(
            conn, chat_id, after=watermark, through=cand.timestamp,
            reason="superseded by newer message", exclude_message_id=cand.message_id,
        )
        luna_db.set_meta(conn, _watermark_key(chat_id), cand.timestamp)
    if operation is None:
        _record_jev_usage(conn, client, decision, cand.message_id)
    else:
        operation.guard = operation.observer = None
    _health(conn, "exhausted" if "resource guard" in decision.reason else "down" if jev_failed else "exhausted" if decision.stage == "guard" else "healthy" if getattr(client, "validated", False) else "unknown", decision.reason,
            validated=bool(getattr(client, "validated", False)))
    _record_judgment(conn, client, decision, cand, now)
    return decision


def _jev_route_label(client: Any) -> str:
    """Cost class of the jev route that answered: ``free`` | ``local`` | ``paid``.

    Chained clients know the serving route's tier; a bare client is classified from its model /
    base_url. The verdict stream shows cost, not internal route names.
    """
    tier = str(getattr(client, "active_tier", "") or "")
    if tier:
        return tier
    serving = getattr(client, "primary", client)
    return route_tier({"model": str(getattr(serving, "model", "") or ""),
                       "base_url": str(getattr(serving, "base_url", "") or "")})


def _record_jev_usage(conn: sqlite3.Connection, client: Any, decision, message_id: str) -> None:
    """Persist what this jev call actually cost, when the provider reports it.

    OpenRouter returns a real ``usage.cost`` in USD; recording it beats estimating from characters,
    so the paid fallback is metered rather than guessed at. Best-effort: never fail a decision.
    """
    usage = getattr(client, "last_usage", None)
    if usage is None:
        return
    served_by = getattr(client, "served_by", "") or ""
    route = ("primary" if served_by.endswith("(primary)") or not served_by
             else f"fallback:{usage.get('provider') or 'unknown'}")
    requested = getattr(getattr(client, "primary", client), "model", None)
    luna_db.record_jev_usage(conn, route=route, usage=usage, requested_model=requested,
                             trigger_message_id=message_id, action=decision.action)


def _settle_seconds() -> int:
    """Seconds a candidate must age before we spend a jev call on it (0 disables).

    Measured on a real 111-message window: at 10s only 41% of messages are ever evaluated, at 20s
    16%. Anything naming Luna bypasses this entirely, so directed replies are never delayed.
    """
    return max(0, int(_num("LUNA_AMBIENT_SETTLE_SECONDS",
                           float(_cfg("ambient.settle_seconds", 10)))))


def _record_wake(conn: sqlite3.Connection, decision, *, now: Optional[datetime] = None) -> None:
    """Record the wake AFTER it was delivered.

    Ordering matters: ``_candidate`` dedups on ``wakes.trigger_message_id``. Recording before delivery
    meant a failed delivery was permanently skipped (the watermark rollback could not re-surface the
    message), so the wake is written only once delivery is confirmed.
    """
    budget = WakeBudget(conn, _wake_policy())
    budget.record(decision.wake_kind, decision.chat_id,
                  trigger_message_id=decision.target_message_id,
                  detail={"value": decision.value, "reason": decision.reason,
                          "emoji": decision.emoji},
                  now=now or datetime.now(timezone.utc))


def _wake_brief(conn: sqlite3.Connection, chat_id: str, decision) -> str:
    """A minimal, persona-neutral nudge: it says *why* there is a turn and hands the voice to SOUL.

    The group surface limits (lines/emoji/markdown) are enforced in code by luna-room's shaping, so the
    brief must not restate them: doing so overrode the persona and made group Luna sound unlike DM
    Luna. It also must not describe the mechanism (SOUL: never discuss how she decides to speak).

    For a directed wake the message being replied to is its own clearly labelled section. The rest of
    the room is explicitly demoted to background: previously the brief said "a message is addressed to
    you" and then listed unrelated chatter with the target buried among them, so replies drifted onto
    whatever else was in the window.
    """
    from luna_core.room import fetch_message
    target = decision.target_message_id or None
    target_row = fetch_message(conn, target, chat_id=chat_id) if target else None
    topic = str(target_row["thread_id"] or "") if target_row is not None else ""
    if decision.directed and target:
        reply_line = _target_lines(conn, target, chat_id=chat_id)
        background = build_room_block(
            conn, chat_id, max_lines=5, max_chars=700, thread_id=topic,
        ).text if _has_other_messages(conn, chat_id, target) else ""
        from luna_core.behaviour_policy import DIRECTED_PROMPT
        head = _cfg("ambient.wake_prompts.directed") or DIRECTED_PROMPT
        parts = [head, "", "The message you are replying to:"]
        if reply_line:
            parts.append(reply_line)
        if background:
            parts += ["", "Room background (context only, do not reply to these):", background]
        return "\n".join(parts)

    block = build_room_block(conn, chat_id, current_message_id=target, max_lines=6, max_chars=900, thread_id=topic)
    from luna_core.behaviour_policy import MESSAGE_PROMPT
    head = (_cfg("ambient.wake_prompts.message") or MESSAGE_PROMPT).replace("{contribution_type}", decision.contribution_type)
    return head + "\n" + block.text


def _target_lines(conn: sqlite3.Connection, message_id: str, *, chat_id: Optional[str] = None) -> str:
    """The replied-to message (with its reply chain) rendered as ``<name>: <text>`` lines."""
    from luna_core.room import build_lines, fetch_message, thread_chain

    row = fetch_message(conn, message_id, chat_id=chat_id)
    if row is None:
        return ""
    chain = thread_chain(conn, message_id, chat_id=chat_id) or [row]
    lines = build_lines(conn, chain, per_line_chars=240)
    return "\n".join(f"{line.name}: {line.content}" for line in lines if line.content)


def _has_other_messages(conn: sqlite3.Connection, chat_id: str, exclude_message_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM messages WHERE chat_id = ? AND message_id != ? LIMIT 1",
        (chat_id, exclude_message_id),
    ).fetchone()
    return row is not None


def _gateway_loop() -> Optional[Any]:
    """The live gateway event loop, resolved at call time.

    ``register()`` runs before the gateway's loop exists and ``pre_gateway_dispatch`` never fires for
    an *unmentioned* group message, so a loop captured at boot is None and the reaction path would be
    dead. The runner publishes its loop on the instance (``_gateway_loop``); read it when we need it.
    """
    if _LOOP is not None:
        return _LOOP
    try:
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
        return getattr(runner, "_gateway_loop", None) if runner is not None else None
    except Exception:
        return None


def _send_reaction(decision) -> bool:
    """Send the reaction on the gateway's event loop via the capability-gated platform facade."""
    actions = getattr(_CTX, "platform_actions", None)
    loop = _gateway_loop()
    if actions is None or loop is None:
        log.warning("[luna-ambient] reaction path unavailable (actions=%s loop=%s)",
                    actions is not None, loop is not None)
        return False
    try:
        async def react():
            if not _still_relevant(decision):
                return {"ok": False}
            return await actions.add_reaction("telegram", decision.chat_id, decision.target_message_id, decision.emoji)
        coro = react()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        result = future.result(timeout=15)
        ok = bool(isinstance(result, dict) and result.get("ok"))
        log.info("[luna-ambient] reaction %s on %s -> %s", decision.emoji,
                 decision.target_message_id, result)
        return ok
    except Exception:
        if "future" in locals():
            future.cancel()
        log.warning("[luna-ambient] reaction send failed", exc_info=True)
        return False


def _brief_key(brief: str) -> str:
    return hashlib.sha256(brief.encode("utf-8")).hexdigest()


def _remember_reply(brief: str, decision: Decision, chat_id: str = "", thread_id: str = "") -> None:
    key = _brief_key(brief)
    with _PENDING_REPLIES_LOCK:
        entries = _PENDING_REPLIES.setdefault(key, [])
        entries.append({
            "trigger_message_id": decision.target_message_id or "-",
            "target_user": decision.target_user or "",
            "target_text": decision.target_text or "",
            "chat_id": chat_id or (decision.chat_id or ""),
            "thread_id": thread_id,
        })
        total = sum(len(items) for items in _PENDING_REPLIES.values())
        for stale_key, stale_entries in list(_PENDING_REPLIES.items()):
            while total >= 64 and stale_entries:
                stale_entries.pop(0)
                total -= 1
                if not stale_entries:
                    _PENDING_REPLIES.pop(stale_key, None)
                    if stale_key != key:
                        break


def _forget_reply(brief: str) -> None:
    key = _brief_key(brief)
    with _PENDING_REPLIES_LOCK:
        entries = _PENDING_REPLIES.get(key) or []
        if entries:
            entries.pop()
        if not entries:
            _PENDING_REPLIES.pop(key, None)


def _inject(brief: str, chat_id: str, decision: Decision) -> bool:
    inject = getattr(_CTX, "inject_message", None)
    if not callable(inject) or not _still_relevant(decision):
        return False
    from luna_core.runtime import worker_context
    context = worker_context()
    identifier = _intent_id(decision)
    from luna_core.room_dispatch import policy
    lease_seconds = policy().max_answer_age_seconds + policy().max_age_seconds + 30
    conn = _index_conn()
    try:
        now = datetime.now(timezone.utc)
        conn.execute("BEGIN IMMEDIATE")
        # A reservation is distinct from a delivered wake; it prevents cross-topic oversubscription.
        pending = conn.execute("SELECT 1 FROM ambient_intents WHERE status='pending' AND expires_at>? LIMIT 1", (now.isoformat(),)).fetchone()
        if pending or conn.execute("SELECT 1 FROM ambient_intents WHERE id=?", (identifier,)).fetchone():
            conn.rollback()
            return False
        conn.execute("INSERT INTO ambient_intents VALUES (?,?,?,?,?,?,?)",
                     (identifier, chat_id, decision.thread_id, str(decision.target_message_id),
                      now.isoformat(), (now + timedelta(seconds=lease_seconds)).isoformat(), "pending"))
        conn.commit()
    finally:
        conn.close()
    _remember_reply(brief, decision, chat_id, decision.thread_id)
    completed = threading.Event()
    receipt_lock = threading.Lock()
    def complete(status, content="", message_id=""):
        with receipt_lock:
            if completed.is_set():
                return
            completed.set()
        def finish():
            _forget_reply(brief)
            conn = _index_conn()
            try:
                conn.execute("UPDATE ambient_intents SET status=? WHERE id=?", (status, identifier))
                conn.commit()
                if status == "delivered":
                    _record_wake(conn, decision)
                    if content:
                        record_luna_reply(conn, message_id=message_id or "luna:wake:" + identifier,
                                          chat_id=chat_id, content=content, thread_id=decision.thread_id)
                    log.info("[luna-ambient] [SAID] event=said trig=%s", decision.target_message_id)
                    _log_verdict(decision, prefix=" [WOKE]")
            finally:
                conn.close()
        context.copy().run(finish)
    delivery = {"allowed": lambda: context.copy().run(_still_relevant, decision),
                "complete": complete, "source_timestamp": decision.source_timestamp}
    try:
        accepted = bool(inject(brief, session_key=_room_session_key(chat_id, decision.thread_id),
                               reply_to_message_id=decision.target_message_id, luna_delivery=delivery))
    except Exception:
        complete("scheduling_failed")
        log.warning("[luna-ambient] inject_message raised", exc_info=True)
        return False
    if not accepted:
        complete("not_admitted")
    return accepted


def _on_post_llm_call(user_message: Any = "", assistant_response: Any = "", **kwargs: Any) -> None:
    # Generation is not delivery. The transport receipt owns indexing and the wake ledger.
    return None


def _on_pre_llm_call(user_message: Any = "", session_id: str = "", **kwargs: Any) -> None:
    """Mark the session as a self-wake turn (our own brief is the user message).

    Internal injected events never reach ``pre_gateway_dispatch``, so this is the only place a
    wake turn can announce itself before the reply is produced.
    """
    try:
        if not isinstance(user_message, str) or not user_message:
            return None
        if _brief_key(user_message) not in _PENDING_REPLIES:
            return None
        with _WAKE_SESSIONS_LOCK:
            _WAKE_SESSIONS[str(session_id)] = True
            while len(_WAKE_SESSIONS) > _MAP_CAP:
                _WAKE_SESSIONS.pop(next(iter(_WAKE_SESSIONS)))
    except Exception:
        log.warning("[luna-ambient] wake session marking failed", exc_info=True)
    return None


def _on_transform_llm_output(response_text: str = "", session_id: str = "", **kwargs: Any) -> Optional[str]:
    """Group hard limits for self-wake replies (luna-room's map cannot see internal turns)."""
    from gateway.response_filters import is_intentional_silence_response
    if is_intentional_silence_response(response_text):
        return response_text
    try:
        with _WAKE_SESSIONS_LOCK:
            marked = bool(_WAKE_SESSIONS.get(str(session_id)))
        if not marked:
            return None
        shaped = shape_group_reply(response_text or "")
        return shaped if shaped != (response_text or "") else None
    except Exception:
        log.warning("[luna-ambient] wake shaping skipped", exc_info=True)
        # Keep privacy and size limits even if the configurable shaping path fails.
        try:
            from luna_core.text import shape_group_reply_minimal

            return shape_group_reply_minimal(response_text or "")
        except Exception:
            return ""


def _log_verdict(decision, *, prefix: str = "") -> None:
    """One INFO line per jev verdict so tuning is evidence-based, not guesswork.

    Previously only wakes were logged and silence was ``debug``, so the operator could not see WHY
    Luna stayed quiet. This prints the gate inputs that actually decided the outcome.
    """
    s = decision.scores or {}
    def g(key: str) -> str:
        v = s.get(key)
        return f"{v:.2f}" if isinstance(v, (int, float)) else "-"
    log.info(
        "[luna-ambient]%s at=%s via=%s verdict=%s directed=%s reason=%s | value=%s addressed=%s "
        "(name=%s direct=%s) add=%s openq=%s fit=%s emojiconf=%s fresh=%s emoji=%s msgfit=%s "
        "timel=%s sens=%s priv=%s vent=%s trig=%s who=%s",
        prefix, fmt_time(datetime.now(timezone.utc)), decision.jev_route or "-",
        decision.action, decision.directed,
        decision.reason,
        f"{decision.value:.3f}" if decision.value else "0", g("addressed"),
        g("addressed_name"), g("addressed_direct"), g("add_value"), g("open_question"),
        g("reaction_fit"), g("emoji_confidence"), g("reaction_freshness"),
        decision.emoji_choice or "-", g("message_would_fit"),
        g("timeliness"), g("sensitive"), g("private"), g("venting"),
        decision.target_message_id or "-", _q(decision.target_user),
    )


def _log_settle(decision: Decision, *, wait_seconds: float = 0.0) -> None:
    if not _mark_not_sent(decision.target_message_id or ""):
        return
    log.info(
        "[luna-ambient] [SETTLE] at=%s event=settle reason=%s | wait=%.1fs trig=%s who=%s",
        fmt_time(datetime.now(timezone.utc)), decision.reason, max(0.0, wait_seconds),
        decision.target_message_id or "-", _q(decision.target_user),
    )


def _jev_paused() -> bool:
    return _JEV_PAUSE_UNTIL > time.monotonic()


def _pause_jev(seconds: float, reason: str = "") -> None:
    global _JEV_PAUSE_UNTIL, _JEV_PAUSE_REASON
    wait = min(max(float(seconds), 1.0), JEV_PAUSE_MAX_SECONDS)
    _JEV_PAUSE_UNTIL = time.monotonic() + wait
    _JEV_PAUSE_REASON = reason
    log.warning(
        "[luna-ambient] jev rate-limited; pausing wake evaluation for %.0fs%s "
        "(no requests will be sent; messages keep being indexed)",
        wait, f" — {reason}" if reason else "",
    )


def _clear_jev_pause() -> None:
    global _JEV_PAUSE_UNTIL, _JEV_PAUSE_REASON
    if _JEV_PAUSE_UNTIL and _JEV_PAUSE_UNTIL <= time.monotonic():
        _JEV_PAUSE_UNTIL = 0.0
        _JEV_PAUSE_REASON = ""
        log.info("[luna-ambient] jev cooldown elapsed; resuming wake evaluation")


def _poll_scope(gateway: Any = None, ctx: Any = None) -> None:
    """One ambient scan. Dry-run logs intended wakes; otherwise injects a turn or sends a reaction."""
    if _cfg("setup.jev", "enabled") != "enabled" or not _flag("LUNA_AMBIENT_ENABLED", bool(_cfg("ambient.enabled", True))):
        return
    chat_id = _ACTIVE_CHAT.get()
    if not chat_id:
        return
    from luna_core.room_dispatch import room_busy
    if room_busy(chat_id, _SCAN_TOPIC.get()):
        return
    dry_run = _dry_run()
    conn = _index_conn()
    try:
        _health(conn, None, "Waiting for eligible room activity")
        if conn.execute("SELECT 1 FROM ambient_intents WHERE status='pending' AND expires_at>? LIMIT 1",
                        (datetime.now(timezone.utc).isoformat(),)).fetchone():
            return  # Do not judge another target while an unsolicited turn is in flight.
        if _JEV_PAUSE_UNTIL and _JEV_PAUSE_UNTIL <= time.monotonic():
            _clear_jev_pause()
        if _jev_paused():
            # Building a client is local. A newly saved route/key must escape
            # the old route's cooldown without waiting for its timer to expire.
            try:
                _jev_client()
            except Exception:
                _health(conn, "down", "Jev route configuration is invalid; review Behaviour")
                return
        if _jev_paused():
            _health(conn, "paused", _JEV_PAUSE_REASON)
            # Deliberately do not evaluate: the watermark stays put so nothing is skipped once jev
            # returns, and the indexer keeps tailing state.db meanwhile. The regex mention fallback
            # still runs — a cooldown must not swallow an explicit "luna" mention.
            _log_unasked_range(
                conn, chat_id, after=luna_db.get_meta(conn, _watermark_key(chat_id), "") or "",
                reason="jev paused",
            )
            fallback = _regex_fallback_decision(conn, chat_id, now=datetime.now(timezone.utc))
            if fallback is None or not fallback.should_wake:
                return
            if dry_run:
                _log_verdict(fallback, prefix=" [DRY-RUN]")
                return
            if not _still_relevant(fallback):
                return
            brief = _wake_brief(conn, chat_id, fallback)
            _inject(brief, chat_id, fallback)
            return
        wm_before = luna_db.get_meta(conn, _watermark_key(chat_id), "") or ""
        decision = evaluate(conn, chat_id, dry_run=dry_run)

        if not decision.should_wake:
            if decision.stage == "scan":
                if decision.reason == "candidate still settling":
                    _log_settle(decision, wait_seconds=float(decision.scores.get("settle_wait_seconds", 0.0)))
                else:
                    log.debug("[luna-ambient] no verdict yet: %s", decision.reason)
                return
            _log_verdict(decision)
            return
        if dry_run:
            _log_verdict(decision, prefix=" [DRY-RUN]")
            return

        if not _still_relevant(decision):
            return
        if decision.action == REACTION:
            ok = _send_reaction(decision)
        else:
            brief = _wake_brief(conn, chat_id, decision)
            ok = _inject(brief, chat_id, decision)

        if ok:
            # Record only now, so a failed delivery above stays retryable.
            with _WAKE_SESSIONS_LOCK:
                _DELIVERY_ATTEMPTS.pop(_intent_id(decision), None)
            if decision.action == REACTION:
                _record_wake(conn, decision)
                _log_verdict(decision, prefix=" [WOKE]")
        else:
            # Delivery failed (e.g. the gateway injector isn't installed yet at boot). Roll the
            # watermark back so the next scan retries this message instead of skipping it — but
            # bounded: an unrecoverable send must not re-spend a jev batch every poll forever.
            attempts = _note_delivery_attempt(_intent_id(decision))
            if attempts >= _DELIVERY_ATTEMPTS_MAX:
                log.warning(
                    "[luna-ambient] wake not delivered after %d attempts (%s); giving up on %s",
                    attempts, decision.action, decision.target_message_id,
                )
            else:
                luna_db.set_meta(conn, _watermark_key(chat_id), wm_before)
                log.warning("[luna-ambient] wake not delivered (%s); will retry next scan",
                            decision.action)
    finally:
        conn.close()


_ACTIVE_CHAT = ContextVar("ambient_chat", default="")


def poll_once(gateway=None, ctx=None):
    global _SCOPE_CURSOR
    if not _enabled():
        return
    conn = _index_conn()
    try:
        _health(conn, None, "Waiting for eligible room activity")
        scopes = []
        for chat in _chat_ids():
            topics = conn.execute("SELECT DISTINCT COALESCE(thread_id, '') topic FROM messages WHERE chat_id=? ORDER BY topic", (chat,)).fetchall()
            scopes.extend((chat, row["topic"]) for row in topics)
        if not scopes:
            return
        chat, topic = scopes[_SCOPE_CURSOR % len(scopes)]
        _SCOPE_CURSOR = (_SCOPE_CURSOR + 1) % len(scopes)
    finally:
        conn.close()
    chat_token, topic_token = _ACTIVE_CHAT.set(chat), _SCAN_TOPIC.set(topic)
    try:
        _poll_scope(gateway, ctx)
    finally:
        _SCAN_TOPIC.reset(topic_token)
        _ACTIVE_CHAT.reset(chat_token)


def _loop(gateway_ref: Dict[str, Any]) -> None:
    while not _STOP.is_set():
        try:
            owner = gateway_ref.get("gateway")
            if owner is not None and not getattr(owner, "_running", False):
                return
            poll_once(owner, _CTX)
        except Exception:
            log.warning("[luna-ambient] scan failed", exc_info=True)
        _STOP.wait(_poll_seconds())


def _ensure_thread(gateway: Any) -> None:
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        _STOP.clear()
        from luna_core.runtime import worker_context
        context = worker_context()
        dry_run = context.run(_dry_run)
        _THREAD = threading.Thread(target=context.run, args=(_loop, {"gateway": gateway}),
                                   name="luna-ambient", daemon=True)
        _THREAD.start()
        log.info("[luna-ambient] poller started (dry_run=%s)", dry_run)


def _on_pre_gateway_dispatch(event: Any = None, gateway: Any = None, **kwargs: Any) -> None:
    global _LOOP
    if _cfg("setup.jev", "enabled") != "enabled" or not _flag("LUNA_AMBIENT_ENABLED", bool(_cfg("ambient.enabled", True))):
        return None
    try:
        # Capture the gateway's loop so the poller thread can send reactions.
        _LOOP = asyncio.get_running_loop()
    except RuntimeError:
        pass
    try:
        _ensure_thread(gateway)
    except Exception:
        log.warning("[luna-ambient] could not start poller", exc_info=True)
    return None


def _in_gateway_process() -> bool:
    # An imported gateway module or environment flag is not a lifecycle owner.
    registered = getattr(getattr(_CTX, "_manager", None), "_gateway_message_injector", None)
    return bool(registered and getattr(registered[0], "_running", False))


def _gateway_ready(gateway=None, **kwargs):
    if gateway is not None and getattr(gateway, "_running", False):
        _ensure_thread(gateway)


def register(ctx) -> None:
    global _CTX, _LOOP
    _CTX = ctx
    cleanup = getattr(ctx, "on_unload", None)
    if callable(cleanup):
        cleanup(_shutdown)
    ctx.register_hook("gateway_ready", _gateway_ready)
    ctx.register_hook("gateway_stopping", lambda **kwargs: _shutdown())
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    # Start watching at gateway boot: with no literal word trigger, no dispatch may ever fire, so a
    # lazy start on pre_gateway_dispatch would never run.
    in_gateway = _in_gateway_process()
    log.info("[luna-ambient] register: gateway=%s argv=%s", in_gateway, sys.argv[:4])
    if in_gateway:
        try:
            _LOOP = asyncio.get_running_loop()
        except RuntimeError:
            _LOOP = None
        try:
            _ensure_thread(None)
        except Exception:
            log.warning("[luna-ambient] boot start failed", exc_info=True)


def _shutdown():
    global _CTX, _LOOP, _CLIENT_CACHE
    _STOP.set()
    if _THREAD and _THREAD is not threading.current_thread():
        _THREAD.join(timeout=2)
    _CTX = _LOOP = _CLIENT_CACHE = None


def _enabled():
    registered = getattr(getattr(_CTX, "_manager", None), "_gateway_message_injector", None)
    if registered and not getattr(registered[0], "_running", False):
        return False
    return (not _STOP.is_set() and _cfg("setup.jev", "enabled") == "enabled"
            and _flag("LUNA_AMBIENT_ENABLED", bool(_cfg("ambient.enabled", False))))


def _intent_revision():
    digest = hashlib.sha256()
    import json
    digest.update(json.dumps(config_read.load_config(), sort_keys=True, default=str).encode())
    for name in ("SOUL.md", ".env"):
        path = _home() / name
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _intent_id(decision):
    import json
    return json.dumps([decision.chat_id, decision.thread_id, decision.target_message_id])


def _still_relevant(decision):
    if not _enabled() or decision.source_revision != _intent_revision():
        return False
    from luna_core.room_dispatch import policy
    try:
        stamp = datetime.fromisoformat(decision.source_timestamp)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        if age < -5 or age >= policy().max_age_seconds:
            return False
        conn = _index_conn()
        try:
            row = conn.execute("SELECT content,thread_id FROM messages WHERE chat_id=? AND message_id=?",
                               (decision.chat_id, decision.target_message_id)).fetchone()
            return bool(row is not None and str(row["thread_id"] or "") == decision.thread_id
                        and hashlib.sha256(strip_media_placeholders(row["content"] or "").encode()).hexdigest() == decision.source_digest)
        finally:
            conn.close()
    except (ValueError, TypeError):
        return False


def _record_judgment(conn, client, decision, candidate, now):
    import json
    from dataclasses import asdict
    answers = getattr(client, "last_answers", None)
    if not answers or not getattr(client, "validated", False):
        return
    # Store no transcript: only media presence and palette literals needed by composition.
    from luna_core.cascade import is_media_only
    cues = "[image]" if is_media_only(candidate.text) else " ".join(e for e in _allowed_reactions() if e in candidate.text)
    conn.execute("INSERT INTO ambient_judgments(chat_id,thread_id,message_id,created_at,answers,original_action,candidate_text,revision) VALUES (?,?,?,?,?,?,?,?)",
                 (candidate.chat_id, _SCAN_TOPIC.get(), candidate.message_id, now.isoformat(),
                  json.dumps({k: {field: value for field, value in asdict(v).items() if field != "legend"}
                              for k, v in answers.items()}), decision.action, cues, _CLIENT_REVISION))
    conn.execute("DELETE FROM ambient_judgments WHERE id NOT IN (SELECT id FROM ambient_judgments ORDER BY id DESC LIMIT 2000)")
    conn.execute("DELETE FROM ambient_intents WHERE created_at<? AND status!='pending'", ((now-timedelta(days=7)).isoformat(),))
    conn.commit()


def _health(conn, status, detail, *, validated=False):
    import json
    from luna_core.jev import route_fingerprint
    revision = route_fingerprint(_cfg("ambient.jev", {}), _jev_api_key, _jev_overrides())
    try:
        previous = json.loads(luna_db.get_meta(conn, "ambient_health", "{}"))
    except ValueError:
        previous = {}
    if previous.get("revision") != revision:
        previous = {}
    current = {"status": status or previous.get("status", "pending"), "detail": detail,
               "heartbeat": datetime.now(timezone.utc).isoformat(), "revision": revision,
               "last_success": datetime.now(timezone.utc).isoformat() if validated else previous.get("last_success")}
    luna_db.set_meta(conn, "ambient_health", json.dumps(current))
