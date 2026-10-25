"""Recipient confusion: in-band identity labels and pending questions never select a target."""
import json
from datetime import datetime, timezone
from pathlib import Path

from gateway.config import Platform
from gateway.platforms.event import MessageEvent
from gateway.session import SessionSource, build_session_key
from luna_core import db
from luna_core.identity import IdentityRegistry
from luna_core.room import build_room_block, record_inbound
from luna_core.room_dispatch import Target, can_deliver


def test_busy_topic_target_and_context_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/room/busy_topics.json").read_text())
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with db.open_db(tmp_path / "luna-state.db") as conn:
        reg = IdentityRegistry(conn)
        for row in fixture["messages"]:
            reg.upsert_auto("telegram", row["user_id"], display_name=row["user_id"])
            record_inbound(conn, message_id=row["message_id"], chat_id=fixture["chat_id"], thread_id=row["topic"],
                           user_id=row["user_id"], content=row["text"], timestamp=now.isoformat())
        selected = next(row for row in fixture["messages"] if row["message_id"] == fixture["selected_message"])
        excluded = frozenset(row["message_id"] for row in fixture["messages"] if row["user_id"] != selected["user_id"])
        block = build_room_block(conn, fixture["chat_id"], thread_id=fixture["topic"], current_message_id=selected["message_id"],
                                 excluded_message_ids=excluded, registry=reg, now=now)
        assert selected["text"] in block.text
        assert "blue badge" not in block.text and "lunch question" not in block.text and "OTHER_TOPIC" not in block.text
        event = MessageEvent(text=selected["text"], message_id=selected["message_id"], source=SessionSource(
            platform=Platform.TELEGRAM, chat_id=fixture["chat_id"], chat_type="forum", thread_id=fixture["topic"], user_id=selected["user_id"]))
        target = Target(str(tmp_path), "telegram", fixture["chat_id"], fixture["topic"], selected["user_id"], selected["message_id"], (selected["message_id"],), excluded, 100, lambda: 1)
        event._luna_reply_target = target
        assert can_deliver(event)
        assert target.user_id == "u_bea" and '"user_id": "u_bea"' in target.note()
        # A person keeps their own warm topic session; changing the current message
        # doesn't select a new cache entry or another person's memory provider.
        first = build_session_key(event.source, thread_sessions_per_user=True)
        event.message_id = "later-message"
        assert build_session_key(event.source, thread_sessions_per_user=True) == first
        event.source.user_id = "u_alex"
        assert build_session_key(event.source, thread_sessions_per_user=True) != first
        assert not can_deliver(event)
