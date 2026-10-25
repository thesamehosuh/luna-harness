"""Dashboard-owned native OpenCode setup and free-model checks."""
from __future__ import annotations

import threading
import uuid
import time
from luna_core.runtime import home

_CATALOG = {}
_CATALOG_LOCK = threading.Lock()

from luna_core.opencode_client import OpenCodeServer, is_free_model, public_model
from luna_core.opencode_install import VERSION, find_binary, install

_OPERATION = threading.Lock()


def status() -> dict:
    from hermes_cli.config import load_config
    found = find_binary()
    configured = load_config().get("model", {})
    configured = configured if isinstance(configured, dict) else {}
    return {"installed": found is not None, "version": found[1] if found else None,
            "recommended_version": VERSION,
            "selected": configured.get("default", "") if configured.get("provider") == "opencode-engine" else ""}


def catalog() -> dict:
    key = str(home())
    with _CATALOG_LOCK:
        cached = _CATALOG.get(key)
        if cached and time.monotonic() - cached[0] < 60:
            return {**status(), "models": list(cached[1])}
        with OpenCodeServer(workspace_key="setup", ephemeral=True) as server:
            models = [public_model(model) for model in server.models() if is_free_model(model)]
        _CATALOG[key] = (time.monotonic(), models)
    return {**status(), "models": models}


def install_engine() -> dict:
    if not _OPERATION.acquire(blocking=False):
        raise RuntimeError("An OpenCode setup operation is already running.")
    try:
        install()
        return status()
    finally:
        _OPERATION.release()


def select_model(model_id: str) -> dict:
    from hermes_cli.config import _CONFIG_LOCK, read_user_config_raw, save_config
    with OpenCodeServer(workspace_key="setup") as server:
        model = next((model for model in server.models() if f"{model.get('providerID')}/{model.get('id')}" == model_id and is_free_model(model)), None)
    if model is None:
        raise ValueError("Choose an available free model from the catalog.")
    with _CONFIG_LOCK:
        config = read_user_config_raw()
        previous = config.get("model")
        previous = previous if isinstance(previous, dict) else {}
        config["model"] = {**previous, "provider": "opencode-engine",
                           "default": model_id, "base_url": "", "api_mode": "chat_completions",
                           "context_length": model.get("limit", {}).get("context", 200000)}
        config["model"].pop("key_env", None)
        config["model"].pop("api_key", None)
        save_config(config)
    return {"ok": True, "model": public_model(model)}


def probe(model_id: str) -> dict:
    if not _OPERATION.acquire(blocking=False):
        raise RuntimeError("An OpenCode setup operation is already running.")
    from luna_core.readiness import fingerprint
    revision = fingerprint()
    try:
        with OpenCodeServer(workspace_key="probe-" + uuid.uuid4().hex, ephemeral=True) as server:
            result = server.run(model=model_id, prompt="Reply exactly OK. Do not use any tools.",
                                instructions="This is a connectivity check. Follow the user request.",
                                timeout=90, max_steps=3)
        response = {"ok": result.text.strip() == "OK", "detail": "Model replied correctly" if result.text.strip() == "OK" else "The model did not pass the response check", "model": model_id, "cost": result.cost}
        from luna_core.readiness import record
        response["verification"] = record("chat", response["ok"], response["detail"], revision=revision, model=model_id)
        return response
    except (RuntimeError, OSError, TimeoutError, ValueError) as exc:
        from luna_core.readiness import record
        verification = record("chat", False, "Model check failed", revision=revision, model=model_id, error_type=type(exc).__name__)
        return {"ok": False, "model": model_id, "detail": str(exc), "verification": verification}
    finally:
        _OPERATION.release()
