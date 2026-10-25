"""Luna companion API (/api/luna/*): endpoint probe + auth gate.

The routes must sit behind the dashboard session-token gate like every other /api/ surface, and
each read endpoint answers with its documented shape. Behaviour covered in
``luna/tests/unit/test_api_models.py``; this tier probes the HTTP surface.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

# Exercise THIS tree's overlay, whatever luna/luna_core the venv has installed.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT / "luna" / "lib"), str(_REPO_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
for _mod in [m for m in sys.modules if m.split(".")[0] in {"luna_core", "luna_cli"}]:
    _origin = getattr(sys.modules[_mod], "__file__", None)
    if _origin and not Path(_origin).resolve().is_relative_to(_REPO_ROOT / "luna/lib"):
        del sys.modules[_mod]

from starlette.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(monkeypatch, tmp_path, _isolate_hermes_home):
    from hermes_constants import get_hermes_home
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    home = get_hermes_home()
    (home / "config.yaml").write_text(
        "luna:\n  ambient:\n    thresholds:\n      message_min_value: 0.55\n",
        encoding="utf-8",
    )
    (home / "logs").mkdir(exist_ok=True)
    monkeypatch.setenv("LUNA_HOME", str(home))
    c = TestClient(app)
    c.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return c


def test_every_luna_route_requires_the_session_token(client):
    """Enumerate the overlay router instead of hand-listing paths.

    A hand-maintained list is how ``/verdicts/stream`` (the one endpoint holding an unbounded
    long-lived connection) came to be the only Luna route with no auth assertion at all.
    """
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME

    from luna_cli.web_routers import router as luna_router

    paths = sorted(
        {
            route.path
            for route in luna_router.routes
            if getattr(route, "path", "").startswith("/api/luna")
        }
    )
    assert len(paths) >= 18, f"expected the full companion surface, saw {paths}"
    # The specific regression this test exists for: the SSE tail was the one route no assertion
    # covered, and it is the one that holds a file handle and a task per connection.
    assert "/api/luna/verdicts/stream" in paths

    bare = TestClient(app)
    bare.headers.pop(_SESSION_HEADER_NAME, None)
    for path in paths:
        response = bare.get(path, params={"token": ""})
        assert response.status_code == 401, f"GET {path} leaked past the auth gate"


def test_health_probe(client):
    data = client.get("/api/luna/health").json()
    assert data["config_exists"] is True
    assert "jev" in data and "jev" in data and "gateway_running" in data


def test_verdicts_and_wakes_shape(client):
    from hermes_constants import get_hermes_home

    (get_hermes_home() / "logs" / "agent.log").write_text(
        '2026-10-02 12:00:01 [luna-ambient] [MSG] at=2026-10-02T12:00:01 via=free '
        # No message text: the verdict log carries ids and weights only (privacy, P5).
        'verdict=message value=0.7 fit=0.6 | who="iris"\n',
        encoding="utf-8",
    )
    events = client.get("/api/luna/verdicts").json()
    assert events["exists"] is True
    assert events["events"] and events["events"][0]["kind"] == "verdict"

    wakes = client.get("/api/luna/wakes").json()
    assert wakes == {"wakes": []}


def test_thresholds_round_trip(client):
    before = client.get("/api/luna/thresholds").json()
    assert before["values"]["message_min_value"]["overridden"] is True

    put = client.put("/api/luna/thresholds", json={"values": {"message_min_fit": 0.5}})
    assert put.status_code == 200
    assert put.json()["results"]["message_min_fit"]["ok"] is True

    after = client.get("/api/luna/thresholds").json()
    assert after["values"]["message_min_fit"]["value"] == 0.5

    rejected = client.put("/api/luna/thresholds", json={"values": {"nope": 1}})
    assert rejected.status_code == 400
    assert "nope" in rejected.json()["detail"]


def test_identity_endpoints(client):
    empty = client.get("/api/luna/identity").json()
    assert empty == {"identities": []}

    created = client.post("/api/luna/identity", json={
        "platform": "telegram", "user_id": "1001",
        "display_name": "Iris", "pronouns": "she/her", "role": "friend",
    })
    assert created.status_code == 200
    assert created.json()["identity"]["display_name"] == "Iris"

    listed = client.get("/api/luna/identity").json()
    assert [i["user_id"] for i in listed["identities"]] == ["1001"]

    merged = client.post("/api/luna/identity/merge", json={"primary": "1001", "alt": "1002"})
    assert merged.status_code == 200
    assert merged.json()["user_id_alt"] == "1002"

    refused = client.post("/api/luna/identity/merge", json={"primary": "1001", "alt": "1001"})
    assert refused.status_code == 400


def test_peers_audit_and_sync_offline(client, monkeypatch):
    from luna_cli import api_models

    monkeypatch.setattr(api_models, "_honcho_store", lambda: None)
    audit = client.get("/api/luna/peers/audit").json()
    assert audit["ok"] is True

    # The route requires an explicit JSON content type (cross-origin no-cors primitives send none).
    sync = client.post("/api/luna/peers/sync", json={}).json()
    assert sync["room"]["error"]  # no honcho configured — reported, not raised
    assert sync["aliases_written"] == 0


def test_replay_error_is_reported(client, monkeypatch):
    from luna_cli import api_models

    monkeypatch.setattr(api_models, "replay", lambda limit=25, recent=10: {"ok": False, "error": "boom"})
    response = client.post("/api/luna/replay", json={"limit": 5, "recent": 5})
    assert response.status_code == 500
    assert response.json()["detail"] == "boom"

    monkeypatch.setattr(api_models, "replay", lambda limit=25, recent=10: {"ok": True, "report": {"rows": []}})
    response = client.post("/api/luna/replay", json={})
    assert response.status_code == 200


def test_onboarding_report_shape(client):
    report = client.get("/api/luna/onboarding").json()
    assert [s["id"] for s in report["steps"]] == ["provider", "telegram", "honcho", "character", "wake_test"]
    assert report["complete"] is False
    assert all({"title", "status", "detail"} <= set(s) for s in report["steps"])


def test_onboarding_personas_and_wake_test(client):
    personas = client.get("/api/luna/onboarding/personas").json()["personas"]
    assert any(p["id"] == "generic" for p in personas)

    report = client.post("/api/luna/onboarding/wake-test", json={"live": False}).json()
    assert report["live"] is False
    assert report["stage0"]["allowed"] is True
    assert "no call spent" in report["detail"]


def test_onboarding_honcho_up_is_mockable(client, monkeypatch):
    from luna_cli import onboarding

    monkeypatch.setattr(onboarding, "honcho_up", lambda timeout=180: {"ok": True, "detail": "stack healthy"})
    response = client.post("/api/luna/onboarding/honcho/up", json={"timeout": 60})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_character_bundle_and_soul_round_trip(client):
    bundle = client.get("/api/luna/character").json()
    assert {"soul", "output", "skins", "skills", "presets"} <= set(bundle)
    assert bundle["current_skin"] in {s["name"] for s in bundle["skins"]}

    saved = client.put("/api/luna/character", json={
        "title": "Testy",
        "intro": "A test persona.",
        "sections": [{"title": "Voice", "body": "Dry."}],
        "footer": "",
    })
    assert saved.status_code == 200
    soul = saved.json()["bundle"]["soul"]
    assert soul["title"] == "Testy"
    assert [s["title"] for s in soul["sections"]] == ["Voice"]

    preset = client.put("/api/luna/character", json={"preset_id": "generic"})
    assert preset.status_code == 200
    assert preset.json()["bundle"]["soul"]["exists"] is True


def test_skin_colors_are_saved_through_the_character_route(client):
    saved = client.put("/api/luna/character", json={
        "skin": "midnight",
        "skin_colors": {"ui_accent": "#0B1020"},
    })
    assert saved.status_code == 200
    skins = saved.json()["bundle"]["skins"]
    assert [s["name"] for s in skins][-1] == "midnight"

    refused = client.put("/api/luna/character", json={
        "skin": "midnight",
        "skin_colors": {"ui_accent": "javascript:alert(1)"},
    })
    assert refused.status_code == 400
