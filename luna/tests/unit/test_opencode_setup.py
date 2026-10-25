"""Dashboard-owned native setup validation and model/key routing."""
from __future__ import annotations

import copy
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from luna_cli import opencode, onboarding, web_routers

FREE = {"id": "test-free", "name": "Test Free", "providerID": "opencode", "enabled": True,
        "cost": [{"input": 0, "output": 0, "cache": {"read": 0, "write": 0}}],
        "capabilities": {"tools": True, "output": ["text"]}, "limit": {"context": 200000}}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("model: {provider: openai, default: paid-model, api_key: synthetic-old-key}\ntelegram: {reactions: true}\n")
    monkeypatch.setattr(opencode, "find_binary", lambda *args: (Path("/synthetic/opencode"), "2.1.2"))
    class Native:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def models(self):
            return [copy.deepcopy(FREE)]
    monkeypatch.setattr(opencode, "OpenCodeServer", Native)
    return tmp_path


def test_select_free_model_preserves_other_settings_and_needs_no_key(home, monkeypatch):
    from hermes_cli.config import load_config
    from luna_core import opencode_install
    monkeypatch.setattr(opencode_install, "find_binary", opencode.find_binary)
    result = opencode.select_model("opencode/test-free")
    assert result["ok"]
    cfg = load_config()
    assert cfg["model"]["provider"] == "opencode-engine"
    assert cfg["model"]["default"] == "opencode/test-free"
    assert cfg["telegram"]["reactions"] is True
    assert "synthetic-old-key" not in (home / "config.yaml").read_text()
    report = onboarding.check_provider()
    assert report["configured"] and report["readiness"] == "configured" and report["key_required"] is False


def test_selection_rejects_unlisted_or_paid_model(home):
    before = (home / "config.yaml").read_text()
    with pytest.raises(ValueError):
        opencode.select_model("opencode/unknown")
    assert (home / "config.yaml").read_text() == before


def test_readiness_proof_must_match_the_selected_native_model(home, monkeypatch):
    from luna_core import readiness, opencode_install
    monkeypatch.setattr(opencode_install, "find_binary", opencode.find_binary)
    opencode.select_model("opencode/test-free")
    readiness.record("chat", True, "Synthetic probe", model="opencode/another-model")
    assert onboarding.check_provider()["status"] == "todo"
    readiness.record("chat", True, "Synthetic probe", model="opencode/test-free")
    assert onboarding.check_provider()["status"] == "done"


def test_setup_supports_legacy_string_model_configuration(home):
    (home / "config.yaml").write_text("model: old-model-name\n")
    assert opencode.status()["selected"] == ""
    assert opencode.select_model("opencode/test-free")["ok"]


def test_runtime_resolution_ignores_paid_keys_and_explicit_endpoint(home, monkeypatch):
    from hermes_cli.runtime_provider import resolve_runtime_provider
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unused-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unrelated.invalid/v1")
    runtime = resolve_runtime_provider(requested="opencode-engine", explicit_api_key="unused-explicit-key", explicit_base_url="https://unrelated.invalid/v1")
    assert runtime["provider"] == "opencode-engine"
    assert runtime["base_url"] == "opencode://local"
    assert runtime["api_key"] == "no-key-required"


def test_all_opencode_routes_require_the_existing_dashboard_token(home, monkeypatch):
    from fastapi import HTTPException
    app = FastAPI()
    app.include_router(web_routers.router)
    def denied():
        raise HTTPException(status_code=401)
    app.dependency_overrides[web_routers._require_token] = denied
    for method, path in [("GET", ""), ("GET", "/models"), ("POST", "/install"), ("PUT", "/model"), ("POST", "/probe")]:
        result = TestClient(app).request(method, "/api/luna/opencode" + path, json={"model": "opencode/test-free"})
        assert result.status_code == 401


def test_model_route_validates_identity_and_reports_probe_failure(home, monkeypatch):
    app = FastAPI()
    app.include_router(web_routers.router)
    app.dependency_overrides[web_routers._require_token] = lambda: None
    client = TestClient(app)
    assert client.put("/api/luna/opencode/model", json={"model": "../other-provider/paid"}).status_code == 422
    assert client.put("/api/luna/opencode/model", json={"model": "opencode/unknown"}).status_code == 400
    monkeypatch.setattr(opencode, "probe", lambda model: {"ok": False, "detail": "Free usage limit reached", "model": model})
    response = client.post("/api/luna/opencode/probe", json={"model": "opencode/test-free"})
    assert response.status_code == 200 and response.json()["ok"] is False
    assert "usage limit" in response.json()["detail"]
