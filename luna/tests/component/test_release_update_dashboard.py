"""The real dashboard routes dispatch Luna's updater and retain the engine guard."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def route(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    from hermes_cli.web_routers import actions
    from hermes_cli import web_server_gateway, web_server_files, web_server
    from luna_cli import release_update
    marker = tmp_path / "code/luna/config/config.yaml.luna"
    marker.parent.mkdir(parents=True)
    marker.write_text("luna: {}")
    monkeypatch.setattr(web_server, "PROJECT_ROOT", tmp_path / "code")
    monkeypatch.setattr(web_server_files, "_dashboard_local_update_managed_externally", lambda: False)
    monkeypatch.setattr(web_server_gateway, "_ACTION_PROCS", {})
    monkeypatch.setattr(web_server_gateway, "_ACTION_RESULTS", {})
    monkeypatch.setattr(web_server_gateway, "_ACTION_COMMANDS", {})
    monkeypatch.setattr(web_server_gateway, "_ACTION_IDS", {})
    monkeypatch.setattr(release_update, "installation", lambda: tmp_path)
    monkeypatch.setattr(release_update, "check", lambda force=False: {"install_method": "luna-release", "update_available": True, "can_apply": True, "latest_version": "0.1.0-alpha.10", "message": "Ready"})
    monkeypatch.setattr(release_update, "require_stopped", lambda root: None)
    app = FastAPI()
    app.include_router(actions.router)
    app.include_router(actions.status_router)
    with TestClient(app) as client:
        yield client, release_update, web_server_gateway


def test_check_uses_luna_published_release_service(route):
    client, _, _ = route
    response = client.get("/api/hermes/update/check?force=true")
    assert response.status_code == 200
    assert response.json()["latest_version"] == "0.1.0-alpha.10"


def test_update_spawns_the_product_module_once(route, monkeypatch):
    client, _, gateway = route
    calls = []
    def spawn(command, name, **kwargs):
        calls.append((command, name, kwargs))
        proc = SimpleNamespace(pid=12345, poll=lambda: None)
        gateway._ACTION_PROCS[name] = proc
        return proc
    monkeypatch.setattr(gateway, "_spawn_hermes_action", spawn)
    assert client.post("/api/hermes/update").json()["ok"] is True
    assert client.post("/api/hermes/update").json()["already_running"] is True
    assert calls == [(["apply"], "hermes-update", {"module": "luna_cli.release_update"})]


def test_live_companion_gets_actionable_refusal_without_spawning(route, monkeypatch):
    client, update, gateway = route
    monkeypatch.setattr(update, "require_stopped", lambda root: (_ for _ in ()).throw(ValueError("Stop your companion in Control Center")))
    monkeypatch.setattr(gateway, "_spawn_hermes_action", lambda *a, **k: pytest.fail("Spawned with active companion"))
    response = client.post("/api/hermes/update")
    assert response.status_code == 409
    assert "Control Center" in response.json()["detail"]


def test_completed_update_reports_reopen_requirement(route, monkeypatch):
    client, update, _ = route
    monkeypatch.setattr(update, "installed_version", lambda root: "0.1.0-alpha.10")
    monkeypatch.setattr(update, "running_version", lambda: "0.1.0-alpha.9")
    # The product marker gates this additive status field.
    from hermes_cli import web_server
    (web_server.PROJECT_ROOT / "luna-release.json").write_text(json.dumps({"version": "0.1.0-alpha.9"}))
    assert client.get("/api/actions/hermes-update/status").json()["restart_required"] is True
