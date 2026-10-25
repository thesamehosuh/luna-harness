"""Real settings/persona round trips in fresh homes, never a developer's profile."""
import json

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from luna_cli import profile_transfer as transfer
from hermes_cli import product_runtime


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    from hermes_cli.config import ensure_hermes_home
    ensure_hermes_home()
    return tmp_path


@pytest.fixture
def bundle():
    return {"format": transfer.FORMAT, "version": 1, "soul": "# Nova\n\nA patient companion.\n\n## Voice\n\nClear and playful.\n",
            "description": "My companion settings", "config": {
                "model": {"provider": "custom", "default": "fixture-model", "base_url": "https://models.example/v1", "api_key": "${TEST_MODEL_KEY}"},
                "dashboard": {"theme": "sakura-day"}, "display": {"skin": "nova"},
                "luna": {"character": {"name": "Nova", "aliases": ["Nova"]},
                         "output": {"max_lines": 7, "allowed_emoji": ["🌱"], "sentence_breaks": False},
                         "memory_stack": {"reasoning_source": "custom", "provider": "custom", "base_url": "https://reasoning.example/v1", "model": "memory-model", "api_key_env": "MEMORY_MODEL_KEY"},
                         "ambient": {"enabled": True, "dry_run": False, "settle_seconds": 15}},
                "honcho": {"dialecticCadence": 12, "contextTokens": 3000},
                "skills": {"auto_load": ["not-installed"]}},
            "skins": {"nova": {"name": "nova", "colors": {"banner_title": "#abcdef"}, "branding": {"agent_name": "Nova"}}}}


def test_import_export_round_trip_retains_settings_and_raw_persona(home, bundle):
    imported = transfer.import_profile("nova", bundle)
    assert imported["name"] == "nova"
    destination = home / "profiles/nova"
    assert (destination / "SOUL.md").read_text() == bundle["soul"]
    exported = transfer.export_profile("nova")
    assert exported["soul"] == bundle["soul"]
    assert exported["skins"] == bundle["skins"]
    assert exported["description"] == bundle["description"]
    assert exported["config"]["model"] == {"api_mode": "chat_completions", **bundle["config"]["model"]}
    assert exported["config"]["honcho"]["dialecticCadence"] == 12
    assert exported["config"]["luna"]["memory_stack"] == bundle["config"]["luna"]["memory_stack"]
    assert exported["config"]["luna"]["output"]["allowed_emoji"] == ["🌱"]
    assert exported["config"]["luna"]["output"]["sentence_breaks"] is False
    # Model references survive, never an expanded value from the exporting process.
    assert "TEST_MODEL_KEY" in json.dumps(exported)
    assert exported["config"]["dashboard"]["theme"] == "sakura-day"
    assert (destination / ".env").stat().st_mode & 0o777 == 0o600
    second = transfer.import_profile("nova-copy", exported)
    assert second["ok"]
    assert transfer.export_profile("nova-copy")["config"] == exported["config"]
    assert not any((destination / name).exists() for name in ("auth.json", "state.db", "luna-state.db", "gateway.pid", "cron/jobs.json"))


def test_export_never_reads_env_history_or_extra_files(home, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "process-literal-should-never-appear")
    (home / ".env").write_text("TEST_MODEL_KEY=env-secret-that-must-stay\n")
    (home / "auth.json").write_text('{"token":"login-secret"}')
    (home / "state.db").write_bytes(b"private-history")
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    cfg["model"].update(default="chosen-model", api_key="literal-key", token="plain-token")
    cfg["providers"] = {"sample": {"base_url": "https://name:password@example.com/v1?key=secret", "api_key": "${TEST_MODEL_KEY}", "key_env": "TEST_MODEL_KEY"}}
    cfg["luna"]["room"]["chat_id"] = "private-room"
    cfg["luna"]["identity"]["peer_prefix"] = "private-person"
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    payload = transfer.export_profile("default")
    encoded = json.dumps(payload)
    for secret in ("process-literal", "env-secret", "login-secret", "private-history", "literal-key", "plain-token", "private-room", "private-person", "name:password"):
        assert secret not in encoded
    assert payload["config"]["providers"]["sample"]["api_key"] == "${TEST_MODEL_KEY}"
    assert payload["config"]["providers"]["sample"]["key_env"] == "TEST_MODEL_KEY"
    assert payload["config"]["providers"]["sample"]["base_url"] == ""


def test_import_resanitizes_external_files_and_keeps_services_off(home, bundle, monkeypatch):
    from hermes_cli import profiles
    monkeypatch.setattr(profiles, "_maybe_register_gateway_service", lambda *a: pytest.fail("Import registered a service"))
    monkeypatch.setattr(profiles, "_notify_multiplexer", lambda *a: pytest.fail("Import notified gateway"))
    bundle["config"]["memory"] = {"memory_enabled": True, "user_profile_enabled": True}
    bundle["config"]["honcho"].update(baseUrl="http://127.0.0.1:12345", workspace="old-workspace", apiKey="secret")
    bundle["config"]["telegram"] = {"bot_token": "old-bot"}
    bundle["config"]["mcp_servers"] = {"unsafe": {"command": "do-something"}}
    bundle["config"]["luna"]["memory_stack"] = {"provider": "old-stack", "api_key": "secret"}
    bundle["config"]["luna"]["setup"] = {"memory": "ready"}
    result = transfer.import_profile("isolated", bundle)
    cfg = yaml.safe_load((home / "profiles/isolated/config.yaml").read_text())
    assert cfg["memory"]["memory_enabled"] is cfg["memory"]["user_profile_enabled"] is False
    assert cfg["luna"]["ambient"]["enabled"] is False
    assert cfg["luna"]["ambient"]["dry_run"] is True
    assert cfg["luna"]["setup"]["memory"] == "pending"
    assert cfg["luna"]["memory_stack"]["reasoning_source"] == "companion"
    assert cfg["honcho"]["baseUrl"] == "http://localhost:8000"
    assert "apiKey" not in cfg["honcho"] and "workspace" not in cfg["honcho"]
    assert result["summary"]["missing_skills"] == ["not-installed"]
    original = json.loads((home / "honcho.json").read_text())["hosts"]["hermes"]["workspace"]
    dest = json.loads((home / "profiles/isolated/honcho.json").read_text())["hosts"]["hermes"]["workspace"]
    assert dest != original and dest != "old-workspace"
    assert not (home / "profiles/isolated/.desktop-preferences.json").exists()


@pytest.mark.parametrize("name", ["default", "../escape", "bad name", ""])
def test_bad_destination_does_not_publish(home, bundle, name):
    before = (home / "config.yaml").read_bytes()
    with pytest.raises(ValueError):
        transfer.import_profile(name, bundle)
    assert (home / "config.yaml").read_bytes() == before


def test_existing_profile_is_never_overwritten(home, bundle):
    transfer.import_profile("nova", bundle)
    existing = (home / "profiles/nova/SOUL.md").read_bytes()
    bundle["soul"] = "# Replacement"
    with pytest.raises(FileExistsError):
        transfer.import_profile("nova", bundle)
    assert (home / "profiles/nova/SOUL.md").read_bytes() == existing


@pytest.mark.parametrize("change", [
    {"version": 2}, {"version": True}, {"soul": ""}, {"config": []},
    {"config": {"luna": {"output": {"max_lines": -5}}}},
    {"config": {"memory": {"memory_enabled": "false"}}},
    {"config": {"agent": {"max_turns": {}}}},
    {"skins": {"../escape": {}}},
    {"skins": {}}, {"soul": "a" * (256 * 1024 + 1)},
])
def test_invalid_file_fails_before_publication(home, bundle, change):
    bundle.update(change)
    with pytest.raises(ValueError):
        transfer.import_profile("rejected", bundle)
    assert not (home / "profiles/rejected").exists()


def test_failed_publish_cleans_staging(home, bundle, monkeypatch):
    def fail(*args):
        raise OSError("simulated disk failure")
    monkeypatch.setattr(transfer.os, "rename", fail)
    with pytest.raises(OSError):
        transfer.import_profile("partial", bundle)
    assert not list((home / "profiles").iterdir())


def test_dashboard_export_preview_import_auth_and_body_limit(home, bundle):
    from luna_cli.web_routers import router, _require_token
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_require_token] = lambda: None
    with TestClient(app) as client:
        exported = client.get("/api/luna/profiles/default/export")
        assert exported.status_code == 200
        assert exported.json()["format"] == transfer.FORMAT
        assert client.post("/api/luna/profiles/preview", json={"bundle": bundle}).status_code == 200
        assert client.post("/api/luna/profiles/import", json={"name": "from-dashboard", "bundle": bundle}).status_code == 200
        assert client.post("/api/luna/profiles/import", json={"name": "from-dashboard", "bundle": bundle}).status_code == 409
        assert client.post("/api/luna/profiles/preview", content="x", headers={"Content-Type": "text/plain"}).status_code == 415
        assert client.post("/api/luna/profiles/preview", content=" " * (transfer.MAX_BYTES + 1), headers={"Content-Type": "application/json"}).status_code == 413
        from fastapi import HTTPException
        def reject():
            raise HTTPException(401, "Token required")
        app.dependency_overrides[_require_token] = reject
        assert client.get("/api/luna/profiles/default/export").status_code == 401
        assert client.post("/api/luna/profiles/import", json={"name": "denied", "bundle": bundle}).status_code == 401


def test_defaults_are_for_new_users_and_partial_configs(home, monkeypatch):
    from hermes_cli.config import load_config
    cfg = load_config()
    assert cfg["model"]["provider"] == "opencode-engine" and cfg["model"]["default"] == ""
    assert cfg["agent"]["reasoning_effort"] == "medium"
    assert cfg["skills"]["auto_load"] == []
    assert cfg["tts"]["enabled"] is False
    assert cfg["memory"]["memory_enabled"] is cfg["memory"]["user_profile_enabled"] is False
    assert cfg["luna"]["ambient"]["enabled"] is False
    assert cfg["luna"]["ambient"]["reactions"]["allowed"] == []
    assert cfg["luna"]["output"]["allowed_emoji"] == []
    assert cfg["luna"]["memory_stack"]["reasoning_source"] == "companion"
    honcho = json.loads((home / "honcho.json").read_text())
    assert honcho["hosts"]["hermes"]["dialecticCadence"] == cfg["honcho"]["dialecticCadence"] == 8
    assert honcho["hosts"]["hermes"]["userPeerAliases"] == {}
    assert (home / "SOUL.md").read_text() == product_runtime.default_soul()
    assert "preferably mean-spirited" not in (home / "SOUL.md").read_text()
    # An older/minimal config gets current product fallbacks without replacing its persona.
    custom_soul = "# Custom\nMy own voice.\n"
    (home / "SOUL.md").write_text(custom_soul)
    (home / "config.yaml").write_text("model: {default: my-model}\nluna: {output: {max_lines: 9}}\n")
    cfg = load_config()
    assert cfg["luna"]["output"]["max_lines"] == 9
    assert cfg["luna"]["ambient"]["enabled"] is False
    assert cfg["memory"]["provider"] == "luna-memory"
    assert cfg["display"]["skin"] == "luna"
    assert cfg["model"]["default"] == "my-model"
    assert (home / "SOUL.md").read_text() == custom_soul
    from luna_cli.character import output_limits, current_skin
    from luna_cli.behaviour import behaviour_bundle
    assert output_limits() == cfg["luna"]["output"]
    assert current_skin() == cfg["display"]["skin"]
    behaviour = behaviour_bundle()
    assert behaviour["enabled"] is False
    assert behaviour["dry_run"] is True
    assert behaviour["poll_seconds"] == cfg["luna"]["ambient"]["poll_seconds"]


def test_seeding_preserves_existing_user_choices(home):
    original = "model: {provider: custom, default: personal-model}\nagent: {reasoning_effort: high}\n"
    (home / "config.yaml").write_text(original)
    (home / "SOUL.md").write_text("# Personal\nMy persona.\n")
    product_runtime.seed_home(home)
    assert (home / "config.yaml").read_text() == original
    assert (home / "SOUL.md").read_text() == "# Personal\nMy persona.\n"
