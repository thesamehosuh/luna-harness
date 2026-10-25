"""Dated, configuration-bound capability checks. Configuration is not verification."""
from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib
import os
import secrets
import time
from functools import wraps

from luna_core import settings
from luna_core.runtime import home


def fingerprint():
    from luna_core import config_read
    from luna_core.honcho import connection_settings
    cfg = config_read.load_config()
    relevant = {"model": cfg.get("model"), "memory": (cfg.get("luna") or {}).get("memory_stack"), "connection": connection_settings()}
    digest = hashlib.sha256(json.dumps(relevant, sort_keys=True).encode())
    env = home() / ".env"
    digest.update(env.read_bytes() if env.exists() else b"")
    return digest.hexdigest()


def record(capability, ok, detail, *, revision=None, **checks):
    path = home() / ".readiness.json"
    with settings.transaction():
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = {}
        value = {"ok": bool(ok), "detail": detail, "checks": checks,
                 "revision": revision or fingerprint(), "at": datetime.now(timezone.utc).isoformat()}
        data[capability] = value
        settings._replace(path, json.dumps(data))
    return value


def get(capability):
    try:
        value = json.loads((home() / ".readiness.json").read_text()).get(capability)
        if value:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(value["at"])).total_seconds()
            stale = value.get("revision") != fingerprint() or age > 86400
            return {**value, "ok": bool(value["ok"] and not stale), "stale": stale}
    except (OSError, ValueError):
        pass
    return None


def verify_memory(*, restart=None):
    from luna_core.honcho import HonchoStore, connection_settings
    from luna_core import config_read
    if config_read.section("luna", "setup", "memory", default="enabled") != "enabled":
        return record("memory", False, "Memory is optional and is not enabled. Open Memory → Setup when you want to enable it.", write_read=False, embedding_search=False, derivation=False, cleanup=True)
    revision = fingerprint()
    marker = "luna-check-" + secrets.token_hex(8)
    connection = connection_settings()
    # Verification owns its entire synthetic workspace, so cleanup cannot remove user facts.
    connection["workspace"] = marker
    checks = {"write_read": False, "embedding_search": False, "derivation": False, "cleanup": False}
    if restart is not None:
        checks.update(peer_attribution=False, room_isolation=False, restart_recall=False)
    client = session = None
    owned_sessions = []
    try:
        store = HonchoStore(**connection)
        client = store.client()
        peer = client.peer("synthetic-peer")
        session = client.session("synthetic-session", peers=["synthetic-peer"])
        owned_sessions.append(session)
        session.add_messages([peer.message(f"My favourite synthetic colour is {marker}.")])
        if restart is not None:
            # Exercise real per-author writes in one room and a separate private session.
            from luna_core.identity import sanitize_peer_id
            first_id, second_id = sanitize_peer_id("1000000001"), sanitize_peer_id("1000000002")
            first, second = client.peer(first_id), client.peer(second_id)
            group = client.session("synthetic-group", peers=[first_id, second_id])
            owned_sessions.append(group)
            first_fact, second_fact = marker + "-author-a", marker + "-author-b"
            group.add_messages([first.message("My synthetic telescope is " + first_fact), second.message("My synthetic bicycle is " + second_fact)])
            private = client.session("synthetic-private", peers=[first_id])
            owned_sessions.append(private)
            secret = marker + "-private-secret"
            private.add_messages([first.message("Keep my synthetic private note " + secret)])
            rows = list(group.messages())
            checks["peer_attribution"] = (any(first_fact in str(getattr(row, "content", "")) and str(getattr(row, "peer_id", "")) == first_id for row in rows)
                and any(second_fact in str(getattr(row, "content", "")) and str(getattr(row, "peer_id", "")) == second_id for row in rows))
            matches = group.search(secret, limit=5)
            checks["room_isolation"] = secret not in str(matches) and secret not in str(group.messages())
            restart()
            persisted = list(group.messages())
            checks["restart_recall"] = any(first_fact in str(getattr(row, "content", "")) for row in persisted) and any(second_fact in str(getattr(row, "content", "")) for row in persisted)
        checks["write_read"] = any(marker in str(getattr(message, "content", "")) for message in session.messages())
        deadline = time.monotonic() + (120 if restart is not None else 30)
        while time.monotonic() < deadline:
            checks["embedding_search"] = bool(session.search(marker, limit=1))
            context = session.context(peer_target="synthetic-peer", limit_to_session=True, search_query=marker)
            representation = getattr(context, "peer_representation", None)
            checks["derivation"] = bool(representation and marker in str(representation))
            if checks["embedding_search"] and checks["derivation"]:
                break
            time.sleep(1)
    except Exception:
        pass
    finally:
        try:
            for owned in owned_sessions:
                owned.delete()
            if client is not None:
                deadline = time.monotonic() + 30
                while True:
                    try:
                        client.delete_workspace(marker)
                        break
                    except Exception:
                        if time.monotonic() >= deadline: raise
                        time.sleep(0.5)
            checks["cleanup"] = True
        except Exception:
            pass
    return record("memory", all(checks.values()), "Memory data-path check completed" if all(checks.values()) else "Memory is degraded; inspect write/read, search, derivation and cleanup checks", revision=revision, **checks)


def verify_chat():
    from luna_core import config_read
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from agent.auxiliary_client import resolve_provider_client
    cfg = config_read.load_config().get("model") or {}
    model = cfg.get("default") or ""
    revision = fingerprint()
    if cfg.get("provider") == "opencode-engine":
        from luna_cli.opencode import probe
        return probe(model)
    client = None
    try:
        runtime = resolve_runtime_provider(requested=cfg.get("provider"), target_model=model)
        client, selected = resolve_provider_client(runtime["provider"], model=model, main_runtime=runtime,
                                                  explicit_base_url=runtime.get("base_url"), explicit_api_key=runtime.get("api_key"), api_mode=runtime.get("api_mode"))
        if client is None:
            raise RuntimeError("No client is configured")
        response = client.chat.completions.create(model=selected or model, messages=[{"role": "user", "content": "Reply exactly OK. Do not use tools."}], timeout=45)
        ok = response.choices[0].message.content.strip() == "OK"
        return record("chat", ok, "Model replied correctly" if ok else "Unexpected model response", revision=revision, model=model)
    except Exception as exc:
        return record("chat", False, "Model check failed", revision=revision, model=model, error_type=type(exc).__name__)
    finally:
        if client and hasattr(client, "close"):
            client.close()
