"""Exercise dashboard JSON through the real request model, transaction and config writer."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("""# retain this comment
telegram:
  group_allowed_chats: [test-room, another-room]
luna:
  setup:
    jev: skipped
  ambient:
    enabled: false
    dry_run: true
    budget:
      old_setting: 42
    jev:
      route: []
      providers: {}
""")
    from luna_cli.web_routers import router
    from hermes_cli.web_server import _active_session_token
    app = FastAPI()
    app.state.auth_required = False
    app.include_router(router)
    with TestClient(app, headers={"X-Hermes-Session-Token": _active_session_token()}) as session:
        yield session


def test_legacy_full_policy_saves_group_selection_and_can_clear_it(client):
    loaded = client.get("/api/luna/behaviour").json()
    assert "old_setting" not in loaded["budget"]
    patch = {key: loaded[key] for key in ("dry_run", "room_register", "budget", "mention_fallback", "reactions", "jev", "conversation")}
    patch.update(watched_chats=["test-room"])
    response = client.put("/api/luna/behaviour", json=patch, headers={"If-Match": loaded["revision"]})
    assert response.status_code == 200, response.text
    assert response.json()["behaviour"]["watched_chats"] == ["test-room"]
    assert client.get("/api/luna/behaviour").json()["watched_chats"] == ["test-room"]
    cleared = client.put("/api/luna/behaviour", json={"watched_chats": []})
    assert cleared.status_code == 200
    assert client.get("/api/luna/behaviour").json()["watched_chats"] == []


def test_master_switch_and_authored_prompts_survive_the_http_request_model(client):
    patch = {"enabled": True, "wake_prompts": {"directed": "Answer warmly."},
             "decision": {"questions": {"message_would_fit": {"instructions": "Would music advice help?"}},
                          "rules": [{"id": "music", "name": "Music", "instructions": "Is this music?", "enabled": True, "action": "reaction", "threshold": 0.8}]},
             "reactions": {"allowed": ["💜"], "criteria": {"💜": "support"}}}
    response = client.put("/api/luna/behaviour", json=patch)
    assert response.status_code == 200, response.text
    for key, value in patch.items():
        assert client.get("/api/luna/behaviour").json()[key] == value
    assert client.put("/api/luna/behaviour", json={"enabled": False}).json()["behaviour"]["enabled"] is False
    assert client.get("/api/luna/behaviour").json()["decision"] == patch["decision"]


def test_invalid_group_returns_a_specific_error_without_writing_other_fields(client):
    response = client.put("/api/luna/behaviour", json={"watched_chats": ["not-allowed"], "room_register": "Do not save this"})
    assert response.status_code == 400
    assert "Choose only Telegram groups" in response.json()["detail"]["watched_chats"]["error"]
    assert client.get("/api/luna/behaviour").json()["room_register"] != "Do not save this"
