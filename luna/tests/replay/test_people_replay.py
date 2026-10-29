"""One person in several rooms: stable identity, scoped basic directory metadata."""
from datetime import datetime, timezone
import json
from pathlib import Path

from luna_core import db, people
from luna_core.identity import IdentityRegistry
from luna_core.room import build_room_block, record_inbound


def test_same_person_in_two_rooms_never_carries_local_roles_between_them(tmp_path, monkeypatch):
    fixture = json.loads((Path(__file__).resolve().parents[1] / "fixtures/people/multiple_groups.json").read_text())
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("memory: {memory_enabled: false, user_profile_enabled: true}\n")
    conn = db.connect(tmp_path / "luna-state.db")
    db.init_db(conn)
    registry = IdentityRegistry(conn)
    ident = registry.upsert_auto(fixture["platform"], fixture["user_id"], display_name=fixture["display_name"])
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    session = {"HERMES_SESSION_PLATFORM": fixture["platform"], "HERMES_SESSION_USER_ID": fixture["user_id"]}
    from gateway import session_context
    monkeypatch.setattr(session_context, "get_session_env", lambda key, default=None: session.get(key, default))
    try:
        for room in fixture["rooms"]:
            record_inbound(conn, message_id="1", chat_id=room["chat_id"], user_id=fixture["user_id"], user_name=fixture["display_name"], content="hello", timestamp=now.isoformat())
            session.update(HERMES_SESSION_CHAT_TYPE="group", HERMES_SESSION_CHAT_ID=room["chat_id"])
            result = json.loads(people.tool_handler({"action": "upsert", "user_id": fixture["user_id"], "aliases": [room["alias"]], "role": room["role"]}))
            assert result["ok"]
        session.update(HERMES_SESSION_CHAT_TYPE="dm", HERMES_SESSION_CHAT_ID=fixture["dm"]["chat_id"])
        assert json.loads(people.tool_handler({"action": "upsert", "user_id": fixture["user_id"], "role": fixture["dm"]["role"]}))["ok"]
        for index, room in enumerate(fixture["rooms"]):
            block = build_room_block(conn, room["chat_id"], current_message_id="1", registry=registry, now=now)
            other = fixture["rooms"][1 - index]
            assert room["role"] in block.text and room["alias"] in block.text
            assert other["role"] not in block.text and other["alias"] not in block.text
            assert fixture["dm"]["role"] not in block.text
            assert block.chars <= 2000
            assert registry.resolve(fixture["platform"], fixture["user_id"]) == ident.peer_id
    finally:
        conn.close()
