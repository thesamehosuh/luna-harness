"""Replay: a recorded/synthetic room window reproduces the expected identity + thread block.

This is the regression gate for the cross-session identity fix. Real captures are anonymized locally;
the committed fixtures are synthetic.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from luna_core import db
from luna_core.identity import IdentityRegistry
from luna_core.room import build_room_block

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "room"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture()
def index(tmp_path):
    conn = db.connect(tmp_path / "luna-state.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _seed(conn, fixture):
    for uid, ident in fixture.get("identity", {}).items():
        conn.execute(
            "INSERT INTO identity(platform, user_id, peer_id, display_name, is_manual) "
            "VALUES ('telegram', ?, ?, ?, 1)",
            (uid, ident["peer_id"], ident.get("display_name")),
        )
    for m in fixture["messages"]:
        conn.execute(
            "INSERT INTO messages(message_id, chat_id, user_id, user_name, peer_id, content, "
            "timestamp, reply_to_message_id, is_bot, observed) VALUES (?,?,?,?,?,?,?,?,0,1)",
            (
                m["message_id"], fixture["chat_id"], m["user_id"], m["user_name"],
                fixture.get("identity", {}).get(m["user_id"], {}).get("peer_id"),
                m["content"], m["timestamp"], m["reply_to_message_id"],
            ),
        )
    conn.commit()


def test_cross_member_reply_chain_is_named(index):
    fixture = _load("cross_member_reply.json")
    _seed(index, fixture)
    registry = IdentityRegistry(index)

    block = build_room_block(
        index, fixture["chat_id"], current_message_id=fixture["current_message_id"],
        registry=registry,
    )
    text = block.text
    assert "Alex" in text
    assert "Babi (replying to Alex): always" in text
    assert "Now Dia (replying to Babi): count me in, that place near the station?" in text
    assert block.lines <= 20


def test_15_member_roster_is_fully_named(index):
    """Required regression: a 15-member roster renders every member by name, none as telegram_<id>."""
    fixture = _load("roster_15.json")
    _seed(index, fixture)
    registry = IdentityRegistry(index)

    block = build_room_block(
        index, fixture["chat_id"], current_message_id=fixture["current_message_id"],
        registry=registry, max_lines=20,
        # Fixtures are dated; pin "now" so the bounded age window does not drop every message.
        now=datetime(2026, 1, 1, 12, 15, tzinfo=timezone.utc),
    )
    text = block.text
    names = [i["display_name"] for i in fixture["identity"].values()]
    assert len(names) == 15
    assert "In the room:" in text
    for name in names:
        assert name in text, f"{name} missing from roster"
    # Room messages remain named. The separate basic directory exposes observed
    # transport IDs deliberately so the constrained people tool can update them.
    assert "telegram_" not in text
    room_text = text.split("[Room context", 1)[-1]
    for m in fixture["messages"]:
        assert m["user_id"] not in room_text


def test_fixture_has_no_real_ids():
    """Guard: committed fixtures must not contain live chat/user ids."""
    for path in FIXTURES.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert str(data.get("chat_id", "")).startswith("-1000000000000")
        for m in data.get("messages", []):
            assert str(m["user_id"]).startswith("u_")
