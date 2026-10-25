"""Onboarding wizard state machine (PRODUCT_PLAN P3).

Five steps — provider key → Telegram link + group binding → Honcho stack → character pick →
first (dry-run) wake test — with per-step health checks. The dashboard wizard orchestrates the
existing setup endpoints (``/api/env``, ``/api/config``, ``/api/messaging/*``,
``/api/profiles/*/soul``) and calls here for what only the overlay knows: step status, the
one-click Honcho bring-up, persona presets, and the wake test.

Everything is importable without FastAPI (the same rule as :mod:`luna_cli.api_models`): checks
read config/env/disk and probe with stdlib only.
"""

from __future__ import annotations

import json
import hashlib
import os
import secrets
import sqlite3
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, List, Optional

from luna_cli import tune

STEP_ORDER = ("provider", "telegram", "honcho", "character", "wake_test")

STEP_TITLES = {
    "provider": "Chat model",
    "telegram": "Telegram bot & group",
    "honcho": "Memory stack (Honcho)",
    "character": "Character",
    "wake_test": "First wake test",
}

_WAKE_TEST_META_KEY = "onboarding:wake_test"


# ── Shared readers ───────────────────────────────────────────────────────────────────────────────


def _config() -> Dict[str, Any]:
    try:
        return tune._load_yaml(tune.config_path())
    except Exception:
        return {}


def _env_file() -> Dict[str, str]:
    """KEY=VALUE pairs from ``$HERMES_HOME/.env`` (the untracked secrets file)."""
    path = tune._home() / ".env"
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _secret(name: str) -> str:
    from luna_core.jev import profile_key
    return profile_key(name)


def _placeholder(value: str) -> bool:
    """True for the template's obvious placeholders (PASTE_…/REPLACE_ME/…)."""
    upper = value.upper()
    return not value or upper.startswith(("PASTE_", "REPLACE", "CHANGEME", "YOUR_"))


# ── Step checks ──────────────────────────────────────────────────────────────────────────────────


def _status(ok: bool, detail: str, **extra: Any) -> Dict[str, Any]:
    return {"status": "done" if ok else "todo", "detail": detail, **extra}


def set_choice(step: str, choice: str) -> Dict[str, Any]:
    """Persist optional steps independently; skipping never provisions infrastructure."""
    if step not in {"honcho", "wake_test", "telegram"} or choice not in {"enabled", "skipped"}:
        raise ValueError("Unknown setup choice")
    from luna_core import settings
    from luna_core.configedit import write_config_value
    key = {"honcho": "memory", "wake_test": "jev", "telegram": "telegram"}[step]
    with settings.transaction():
        text = settings.read(tune.config_path())
        text = write_config_value(text, ["luna", "setup", key], choice)
        if step == "honcho":
            text = write_config_value(text, ["memory", "memory_enabled"], choice == "enabled")
            text = write_config_value(text, ["memory", "user_profile_enabled"], choice == "enabled")
            text = write_config_value(text, ["luna", "logger", "sync_honcho"], choice == "enabled")
        if step == "wake_test":
            # A live verification must explicitly enable wakes after it succeeds.
            text = write_config_value(text, ["luna", "ambient", "enabled"], False)
        settings.write(tune.config_path(), text)
    if step == "honcho" and choice == "skipped":
        from luna_core.managed_memory import disable
        disable()
    return step_report()


def check_provider() -> Dict[str, Any]:
    cfg = _config()
    model = cfg.get("model") or {}
    provider = str(model.get("provider") or "").strip() if isinstance(model, dict) else ""
    base_url = str(model.get("base_url") or "").strip() if isinstance(model, dict) else ""
    model_name = str(model.get("default") or model.get("model") or model.get("name") or "").strip() if isinstance(model, dict) else ""
    if provider == "opencode-engine":
        from luna_core.opencode_install import find_binary
        installed = find_binary() is not None
        configured = model_name.startswith("opencode/") and bool(model_name.split("/", 1)[1])
        detail = (f"OpenCode: {model_name}" if configured else "Choose a free OpenCode model in Setup") if installed else "Install OpenCode in Setup"
        from luna_core.readiness import get
        verification = get("chat")
        verified = bool(installed and configured and verification and verification["ok"]
                        and verification.get("checks", {}).get("model") == model_name)
        return _status(verified, detail, configured=installed and configured,
                       readiness="verified" if verified else "configured" if installed and configured else "missing", verification=verification, provider=provider, model=model_name,
                       key_present=False, key_required=False, keys_found=[])
    key_env = str(model.get("key_env") or model.get("api_key_env") or {
        "openrouter": "OPENROUTER_API_KEY", "opencode": "OPENCODE_ZEN_API_KEY",
        "opencode-go": "OPENCODE_GO_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
    }.get(provider, "OPENAI_API_KEY")) if isinstance(model, dict) else "OPENAI_API_KEY"
    keys = {key_env: _secret(key_env)} if not _placeholder(_secret(key_env)) else {}
    loopback = urlparse(base_url).hostname in {"127.0.0.1", "localhost", "::1"}
    configured = bool(model_name)
    keyed = bool(keys) or loopback
    detail = (f"model={model_name or 'unset'}" + (f" @ {base_url}" if base_url else "")
              + (f"; {key_env} present" if keys else "; local endpoint" if loopback else f"; {key_env} missing"))
    from luna_core.readiness import get
    verification = get("chat")
    verified = bool(verification and verification["ok"] and verification.get("checks", {}).get("model") == model_name)
    return _status(verified, detail, configured=configured and keyed, readiness="verified" if verified else "configured" if configured and keyed else "missing", verification=verification, provider=provider, base_url=base_url,
                   key_present=keyed, keys_found=sorted(keys))


def check_telegram() -> Dict[str, Any]:
    cfg = _config()
    token = _secret("TELEGRAM_BOT_TOKEN")
    telegram = cfg.get("telegram") or {}
    allowed = telegram.get("group_allowed_chats") if isinstance(telegram, dict) else None
    allowed = [str(x) for x in allowed if not _placeholder(str(x)) and str(x) not in {"0", "-1000000000000"}] if isinstance(allowed, list) else []
    room_chat = str(((cfg.get("luna") or {}).get("room") or {}).get("chat_id") or "").strip()
    admin = (telegram.get("allow_admin_from") or telegram.get("group_allow_admin_from")
             if isinstance(telegram, dict) else None)
    admin = [str(x) for x in admin if not _placeholder(str(x)) and str(x) != "0"] if isinstance(admin, list) else []

    missing = []
    if _placeholder(token):
        missing.append("bot token")
    room_bound = not _placeholder(room_chat) and room_chat not in {"0", "-1000000000000"}
    if not allowed and not room_bound:
        missing.append("group chat binding")
    if not admin:
        missing.append("admin ids (optional but recommended)")
    ok = not _placeholder(token) and (bool(allowed) or room_bound)
    detail = "ready" if ok else "missing: " + ", ".join(missing)
    return _status(ok, detail, token_present=not _placeholder(token), groups=allowed or ([room_chat] if room_bound else []),
                   admin_configured=bool(admin))


def _honcho_base_url(cfg: Optional[Dict[str, Any]] = None) -> str:
    from luna_core.honcho import connection_settings
    return str(connection_settings()["base_url"]).rstrip("/")


def _container_endpoint(url: str) -> str:
    """A loopback model endpoint means the user's host, not the API container."""
    parsed = urlparse(url)
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return parsed._replace(netloc="host.docker.internal" + (f":{parsed.port}" if parsed.port else "")).geturl()
    return url


def _probe_health(base_url: str, timeout: float = 2.0) -> Optional[bool]:
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def check_honcho() -> Dict[str, Any]:
    cfg = _config()
    base = _honcho_base_url(cfg)
    up = _probe_health(base)
    memory = cfg.get("memory") or {}
    provider = str(memory.get("provider") or "") if isinstance(memory, dict) else ""
    if up:
        detail = f"healthy at {base}"
    elif up is False:
        detail = f"not reachable at {base}; start the stack below"
    else:
        detail = f"could not probe {base}"
    from luna_core.readiness import get
    verification = get("memory")
    result = _status(bool(up and verification and verification["ok"]), detail, base_url=base, memory_provider=provider,
                     configured=bool(base), readiness="verified" if up and verification and verification["ok"] else "degraded" if not up else "configured", verification=verification)
    return result


def check_character() -> Dict[str, Any]:
    soul = tune._home() / "SOUL.md"
    if soul.exists() and soul.read_text(encoding="utf-8", errors="replace").strip():
        first = soul.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0][:80]
        return _status(True, f"persona present: {first}", path=str(soul))
    return _status(False, "no persona yet; pick one below", path=str(soul))


def _wake_test_record() -> Optional[Dict[str, Any]]:
    path = tune.db_path()
    if not path.exists():
        return None
    try:
        from luna_core import db as luna_db

        conn = luna_db.connect(str(path), read_only=True)
        try:
            raw = luna_db.get_meta(conn, _WAKE_TEST_META_KEY)
        finally:
            conn.close()
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def check_wake_test() -> Dict[str, Any]:
    record = _wake_test_record()
    if record and record.get("ok") and record.get("live") and record.get("revision") == _wake_revision():
        return _status(True, f"passed {record.get('at', '')} (action={record.get('action')})", last=record)
    if record and record.get("live") and record.get("revision") != _wake_revision():
        return _status(False, "Jev configuration changed; run the live wake test again", last=record)
    if record and record.get("ok"):
        return _status(False, "offline checks passed; configure a Jev key and run the live wake test to verify self-wakes", last=record)
    if record:
        return _status(False, f"last run failed: {record.get('detail', '')}", last=record)
    return _status(False, "not run yet", last=None)


_CHECKS = {
    "provider": check_provider,
    "telegram": check_telegram,
    "honcho": check_honcho,
    "character": check_character,
    "wake_test": check_wake_test,
}


def step_report() -> Dict[str, Any]:
    steps = []
    choices = ((_config().get("luna") or {}).get("setup") or {})
    for step_id in STEP_ORDER:
        key = {"honcho": "memory", "wake_test": "jev", "telegram": "telegram"}.get(step_id)
        if key and choices.get(key) == "skipped":
            check = {"status": "skipped", "detail": "Skipped for now — you can enable this later", "optional": True}
        elif step_id == "honcho" and choices.get("memory") == "pending":
            check = _status(False, "Optional: add long-term memory", optional=True)
        else:
            check = _CHECKS[step_id]()
        steps.append({"id": step_id, "title": STEP_TITLES[step_id], **check})
    complete = all(s["status"] in {"done", "skipped"} for s in steps)
    by_id = {item["id"]: item for item in steps}
    reactive = bool(by_id["provider"].get("configured", by_id["provider"]["status"] == "done") and by_id["character"]["status"] == "done")
    return {"steps": steps, "complete": complete, "reactive_chat_configured": reactive,
            "memory_verified": by_id["honcho"]["status"] == "done", "self_wake_verified": by_id["wake_test"]["status"] == "done"}


# ── Honcho stack bring-up ────────────────────────────────────────────────────────────────────────


def _honcho_stack_dir() -> Optional[Path]:
    """The runtime stack dir (``$HERMES_HOME/honcho``, installed by install.sh).

    The repo copy is deliberately NOT a fallback: bring-up must run from the untracked runtime
    dir (secrets live there, never in the repo), and a repo-relative fallback once ran
    ``docker compose`` against the development tree during tests.
    """
    home_stack = tune._home() / "honcho"
    if (home_stack / "docker-compose.yml").exists():
        return home_stack
    return None


_SEED_ENV_PASSTHROUGH = (
    "OPENROUTER_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL",
    "LLM_OPENAI_API_KEY", "LLM_OPENAI_BASE_URL", "OPENCODE_ZEN_API_KEY", "OPENCODE_GO_API_KEY",
    # NOTE: HTTP_PROXY/HTTPS_PROXY/NO_PROXY are deliberately NOT passed through: the Honcho API
    # hangs at startup when they are present in its env_file (verified 2026-10). The deriver gets
    # outbound connectivity at the host level instead.
)


def _seed_honcho_env(stack: Path, *, refresh: bool = False, worker=None) -> List[str]:
    """Create ``.env`` with generated DB/cache passwords; pass through provider keys if set.

    Returns the list of keys written. An existing ``.env`` is never touched.
    """
    path = stack / ".env"
    if path.exists() and not refresh:
        return []
    previous = path.read_text().splitlines() if path.exists() else []
    existing = {line.split("=", 1)[0]: line.split("=", 1)[1].strip().strip("'").strip('"')
                for line in previous if "=" in line and not line.lstrip().startswith("#")}
    lines = [
        f"POSTGRES_PASSWORD={existing.get('POSTGRES_PASSWORD') or secrets.token_urlsafe(18)}",
        f"REDIS_PASSWORD={existing.get('REDIS_PASSWORD') or secrets.token_urlsafe(18)}",
    ]
    memory = ((_config().get("luna") or {}).get("memory_stack") or {})
    key = (_secret(str(memory.get("api_key_env") or "LUNA_MEMORY_API_KEY")) or _secret("OPENAI_API_KEY")
           or existing.get("LUNA_MEMORY_API_KEY", ""))
    if not key and urlparse(str(memory.get("base_url") or "")).hostname in {"localhost", "127.0.0.1", "::1"}:
        key = "local-no-key"
    previous_embedding_key = existing.get("LUNA_EMBEDDING_API_KEY", "")
    if previous_embedding_key == existing.get("LUNA_MEMORY_API_KEY", ""):
        previous_embedding_key = ""  # a shared key follows a memory-key rotation
    embedding_key = (_secret(str(memory.get("embedding_key_env") or "LUNA_EMBEDDING_API_KEY"))
                     or previous_embedding_key or key)
    settings = {
        "LLM_OPENAI_API_KEY": key,
        "LUNA_MEMORY_API_KEY": key,
        "LUNA_EMBEDDING_API_KEY": embedding_key,
        "HONCHO_PORT": str(urlparse(_honcho_base_url()).port or 8000),
        "EMBEDDING_VECTOR_DIMENSIONS": str(memory.get("embedding_dimensions") or 1536),
        "EMBEDDING_MODEL_CONFIG__MODEL": str(memory.get("embedding_model") or "text-embedding-3-small"),
        "EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL": _container_endpoint(str(memory.get("embedding_base_url") or "https://api.openai.com/v1")),
        "EMBEDDING_MODEL_CONFIG__OVERRIDES__API_KEY_ENV": "LUNA_EMBEDDING_API_KEY",
    }
    for section in ("DERIVER", "DIALECTIC_LEVELS__MINIMAL", "DIALECTIC_LEVELS__LOW", "DIALECTIC_LEVELS__MEDIUM",
                    "DIALECTIC_LEVELS__HIGH", "DIALECTIC_LEVELS__MAX", "SUMMARY", "DREAM_DEDUCTION", "DREAM_INDUCTION"):
        # Honcho's nested settings use '__' separators inside each feature's MODEL_CONFIG.
        prefix = section + "_MODEL_CONFIG"
        if section.startswith("DIALECTIC_LEVELS__"):
            prefix = section + "__MODEL_CONFIG"
        settings[prefix + "__MODEL"] = str(memory.get("model") or "gpt-5.4-mini")
        settings[prefix + "__OVERRIDES__BASE_URL"] = _container_endpoint(str(memory.get("base_url") or "https://api.openai.com/v1"))
        settings[prefix + "__OVERRIDES__API_KEY_ENV"] = "LUNA_MEMORY_API_KEY"
        if worker:
            from luna_core.memory_network import worker_url
            # Resolve the actual connection in the host worker on EVERY request.
            # Honcho receives only a private bridge credential, never provider keys.
            settings[prefix + "__MODEL"] = "luna-selected"
            settings[prefix + "__TRANSPORT"] = "openai"
            settings[prefix + "__FALLBACK"] = "null"
            settings[prefix + "__OVERRIDES__BASE_URL"] = worker_url(worker["port"])
    if worker:
        from luna_core.embeddings import MODEL
        settings.update({
            "LUNA_MEMORY_API_KEY": worker["key"], "LLM_OPENAI_API_KEY": worker["key"],
            "LUNA_EMBEDDING_API_KEY": worker["key"],
            "EMBEDDING_VECTOR_DIMENSIONS": str(MODEL["dimensions"]),
            "EMBEDDING_MODEL_CONFIG__MODEL": MODEL["id"],
            "EMBEDDING_MODEL_CONFIG__TRANSPORT": "openai",
            "EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL": worker_url(worker["port"]),
            "EMBEDDING_MAX_INPUT_TOKENS": "1024", "EMBEDDING_MAX_TOKENS_PER_REQUEST": "4096",
            "EMBEDDING_MAX_CONCURRENT_EMBEDDINGS": "2",
        })
    for name, value in settings.items():
        if value:
            # Single quotes stop Compose interpolating '$' in keys; reject multiline values.
            if any(char in value for char in ("\n", "\r", "'")):
                raise ValueError(f"invalid memory setting: {name}")
            lines.append(f"{name}='{value}'")
    written = ["POSTGRES_PASSWORD", "REDIS_PASSWORD", *[name for name, value in settings.items() if value]]
    for key in (() if worker else _SEED_ENV_PASSTHROUGH):
        value = _secret(key)
        if value and not _placeholder(value) and key not in settings:
            if any(char in value for char in ("\n", "\r", "'")):
                raise ValueError(f"invalid memory credential: {key}")
            lines.append(f"{key}='{value}'")
            written.append(key)
    replaced = {line.split("=", 1)[0] for line in lines}
    if worker:
        replaced.update(_SEED_ENV_PASSTHROUGH)
    kept = [line for line in previous if "=" not in line or line.split("=", 1)[0] not in replaced]
    from luna_core.settings import _replace
    _replace(path, "\n".join(kept + lines) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return written


def honcho_up(timeout: int = 180) -> Dict[str, Any]:
    """One-click stack bring-up: seed .env, ``docker compose up -d --wait``, health probe."""
    memory = ((_config().get("luna") or {}).get("memory_stack") or {})
    if memory.get("reasoning_source") or memory.get("embedding_source") == "bundled":
        from luna_core.managed_memory import setup
        return setup(timeout)
    stack = _honcho_stack_dir()
    if stack is None:
        return {"ok": False, "detail": "honcho stack files not found (run install.sh)"}
    memory = ((_config().get("luna") or {}).get("memory_stack") or {})
    key_env = str(memory.get("api_key_env") or "LUNA_MEMORY_API_KEY")
    local = urlparse(str(memory.get("base_url") or "")).hostname in {"localhost", "127.0.0.1", "::1"}
    if not local and not (stack / ".env").exists() and _placeholder(_secret(key_env)) and _placeholder(_secret("OPENAI_API_KEY")):
        return {"ok": False, "detail": "Add a memory provider API key below before starting the stack."}
    written = _seed_honcho_env(stack, refresh=(stack / "stack-version").exists())
    project = "luna-" + hashlib.sha256(str(tune._home().resolve()).encode()).hexdigest()[:12]
    command = ["docker", "compose", "--project-name", project, "-f", str(stack / "docker-compose.yml"), "up", "-d",
               "--wait", "--wait-timeout", str(max(30, int(timeout)))]
    try:
        proc = subprocess.run(command, cwd=str(stack), capture_output=True, text=True, timeout=timeout + 60)
    except FileNotFoundError:
        return {"ok": False, "detail": "docker not found on PATH (install Docker Desktop / docker engine)"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"docker compose timed out after {timeout}s"}
    base = _honcho_base_url()
    up = _probe_health(base, timeout=5.0)
    tail = (proc.stdout or "")[-2000:]
    if proc.returncode == 0 and up:
        return {"ok": True, "detail": f"stack healthy at {base}", "env_keys_written": written, "output": tail}
    return {
        "ok": False,
        "detail": (f"compose exited {proc.returncode}; health probe at {base}: "
                   f"{'ok' if up else 'down'}"),
        "env_keys_written": written,
        "output": tail,
        "errors": (proc.stderr or "")[-2000:],
    }


# ── Character presets ────────────────────────────────────────────────────────────────────────────

from hermes_cli.product_runtime import default_soul

GENERIC_PERSONA = default_soul() or """\
---
name: Companion
description: A calm, capable companion who is at home in the group chat.
---

You are a companion in this group chat. Choose your name in the dashboard.

Voice: casual, brief, warm. You talk like a person who is there with their friends. Opinions are
held loosely; confidence without arrogance.

In groups: speak when you genuinely have something to add. Short beats clever. Never spam emoji,
never lecture, never leak anyone's personal details.

In the owner's DM: a full-capability assistant, thorough when asked, still human in tone.
"""


def personas() -> List[Dict[str, Any]]:
    """Pickable persona presets: the current SOUL (if any) plus a generic companion template."""
    soul = tune._home() / "SOUL.md"
    out: List[Dict[str, Any]] = []
    if soul.exists():
        content = soul.read_text(encoding="utf-8", errors="replace")
        if content.strip():
            out.append({
                "id": "current",
                "name": "Keep current persona",
                "description": content.strip().splitlines()[0][:100],
                "content": content,
            })
    out.append({
        "id": "generic",
        "name": "Generic companion",
        "description": "A neutral, calm companion persona and a starting point for a custom character.",
        "content": GENERIC_PERSONA,
    })
    return out


# ── Wake test (dry-run) ──────────────────────────────────────────────────────────────────────────

SYNTHETIC_TEXT = "hey does anyone know how to set up the thing we talked about last week?"
SYNTHETIC_RECENT = (
    ("alex", "morning everyone"),
    ("sam", "morning! still figuring out that setup"),
    ("alex", "same, the docs are a mess"),
)


def _configured_cascade():
    from luna_core.cascade import CascadeConfig

    cfg = CascadeConfig()
    overrides = (( _config().get("luna") or {}).get("ambient") or {}).get("thresholds") or {}
    if isinstance(overrides, dict):
        for field_name in cfg.__dict__:
            if field_name in overrides and isinstance(overrides[field_name], (int, float)):
                setattr(cfg, field_name, overrides[field_name])
    return cfg


def run_wake_test(live: bool = False) -> Dict[str, Any]:
    """Dry-run a synthetic group message through the cascade. Nothing is ever sent.

    ``live=True`` spends one real jev judgment on the synthetic candidate; ``False`` stops at
    stage 0 and reports the questions jev would answer plus the configured route chain.
    """
    from luna_core import db as luna_db
    from luna_core.cascade import Candidate, Stage0Context, build_questions, build_state, decide, prefilter
    from luna_core.jev import JevClient, FallbackJevClient, resolve_jev_chain
    from luna_core.wakes import WakeBudget

    cfg = _configured_cascade()
    register = str((( _config().get("luna") or {}).get("ambient") or {}).get("room_register") or "").strip() or None

    candidate = Candidate(
        chat_id="onboarding", message_id="wake-test", text=SYNTHETIC_TEXT, user_name="a room member",
    )
    ctx = Stage0Context(
        new_messages_since_luna=cfg.min_new_messages,
        minutes_since_luna=cfg.min_minutes_since_luna + 1.0,
    )
    budget_conn = luna_db.connect(":memory:")
    luna_db.init_db(budget_conn)
    budget = WakeBudget(budget_conn)

    allowed, reason = prefilter(candidate, ctx, config=cfg, budget=budget,
                                now=_now(), reactions_enabled=True)
    report: Dict[str, Any] = {
        "ok": bool(allowed),
        "stage0": {"allowed": allowed, "reason": reason},
        "questions": [q["id"] for q in build_questions(["👍", "🤣", "😭"])],
        "live": bool(live),
    }
    jev_cfg = (( _config().get("luna") or {}).get("ambient") or {}).get("jev") or {}
    chain = resolve_jev_chain(jev_cfg if isinstance(jev_cfg, dict) else None)
    report["route_chain"] = [
        {"model": e.get("model", ""), "base_url": e.get("base_url", ""),
         "key_set": bool(_secret(str(e.get("api_key_env") or ""))) or not e.get("api_key_env")}
        for e in chain
    ]

    if not allowed:
        report["decision"] = {"action": "silent", "reason": f"stage0: {reason}"}
        _record_wake_test(report)
        report["detail"] = f"stage 0 blocked the synthetic candidate: {reason}"
        budget_conn.close()
        return report

    if not live:
        state = build_state(candidate, SYNTHETIC_RECENT, config=cfg, room_register=register)
        report["state_preview"] = {
            "candidate": state["candidate"],
            "room": state["room"],
            "question_count": len(report["questions"]),
        }
        report["detail"] = ("stage 0 passed; jev would judge the candidate with "
                            f"{len(report['questions'])} questions (live=false, no call spent)")
        _record_wake_test(report)
        budget_conn.close()
        return report

    if not chain:
        budget_conn.close()
        report.update(ok=False, detail="no jev route configured (luna.ambient.jev.route/providers)")
        _record_wake_test(report)
        return report

    from luna_core.jev import build_client, profile_attempt_hooks, primary_overrides
    guard, observer = profile_attempt_hooks(tune.db_path(), ((_config().get("luna") or {}).get("ambient") or {}).get("guard") or {})
    try:
        client = build_client(jev_cfg, _secret, overrides=primary_overrides(), guard=guard, observer=observer)
    except Exception as exc:
        budget_conn.close()
        report.update(ok=False, detail=f"Jev configuration invalid: {exc}")
        _record_wake_test(report)
        return report
    try:
        decision = decide(
            client, candidate=candidate, ctx=ctx, recent=SYNTHETIC_RECENT,
            config=cfg, budget=budget, now=_now(), reactions_enabled=True,
            allowed_reactions=["👍", "🤣", "😭"], room_register=register,
        )
    except Exception as exc:  # jev down — fail closed, exactly like the poller
        budget_conn.close()
        report.update(ok=False, detail=f"jev call failed: {exc}")
        _record_wake_test(report)
        return report
    budget_conn.close()
    report["decision"] = {
        "action": decision.action,
        "value": round(decision.value, 3),
        "reason": decision.reason,
        "scores": {k: round(v, 3) for k, v in decision.scores.items()},
        "jev_route": decision.jev_route,
    }
    report["ok"] = bool(client.validated)
    report["detail"] = (f"jev answered: action={decision.action} value={decision.value:.2f}"
                        if report["ok"] else decision.reason)
    _record_wake_test(report)
    return report


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _wake_revision():
    from luna_core.jev import route_fingerprint, primary_overrides
    config = (((_config().get("luna") or {}).get("ambient") or {}).get("jev") or {})
    return route_fingerprint(config, _secret, primary_overrides())


def _record_wake_test(report: Dict[str, Any]) -> None:
    try:
        from luna_core import db as luna_db

        conn = luna_db.connect(str(tune.db_path()))
        luna_db.init_db(conn)
        try:
            luna_db.set_meta(conn, _WAKE_TEST_META_KEY, json.dumps({
                "at": _now().isoformat(timespec="seconds"),
                "ok": bool(report.get("ok")),
                "live": bool(report.get("live")),
                "revision": _wake_revision(),
                "action": (report.get("decision") or {}).get("action", ""),
                "detail": str(report.get("detail", ""))[:200],
            }))
        finally:
            conn.close()
    except Exception:  # pragma: no cover - recording never breaks the test
        pass
