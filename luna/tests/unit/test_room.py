"""Room + cross-session thread reconstruction."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from luna_core import db
from luna_core.identity import IdentityRegistry
from luna_core.room import (
    build_room_block,
    reply_author_peer_id,
    render_block,
    thread_chain,
)

CHAT = "-100123"
ALEX, BABI, DIA = "1001", "1002", "1003"


@pytest.fixture()
def env(tmp_path):
    conn = db.connect(tmp_path / "luna-state.db")
    db.init_db(conn)
    reg = IdentityRegistry(conn)
    reg.set_manual("telegram", ALEX, peer_id="alex", display_name="Alex")
    reg.set_manual("telegram", BABI, peer_id="babi", display_name="Babi")
    reg.set_manual("telegram", DIA, peer_id="dia", display_name="Dia")
    yield conn, reg
    conn.close()


def _add(conn, mid, uid, text, ts, *, reply_to=None, name=None, is_bot=0):
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, user_id, user_name, content, timestamp, "
        "reply_to_message_id, is_bot, observed) VALUES (?,?,?,?,?,?,?,?,1)",
        (mid, CHAT, uid, name or uid, text, ts, reply_to, is_bot),
    )
    conn.commit()


def _iso(minutes):
    return datetime(2026, 1, 1, 12, minutes, tzinfo=timezone.utc).isoformat()


def test_thread_chain_follows_reply_edges(env):
    conn, _ = env
    _add(conn, "101", ALEX, "anyone up for pizza", _iso(0))
    _add(conn, "104", BABI, "always", _iso(5), reply_to="101")
    _add(conn, "107", DIA, "count me in", _iso(9), reply_to="104")

    chain = thread_chain(conn, "107")
    assert [r["message_id"] for r in chain] == ["101", "104", "107"]


def test_room_block_names_authors_and_reply_targets(env):
    conn, reg = env
    _add(conn, "101", ALEX, "anyone up for pizza", _iso(0))
    _add(conn, "104", BABI, "always", _iso(5), reply_to="101")
    _add(conn, "107", DIA, "count me in", _iso(9), reply_to="104")

    block = build_room_block(
        conn, CHAT, current_message_id="107", registry=reg,
        now=datetime(2026, 1, 1, 12, 10, tzinfo=timezone.utc),
    )
    assert "Alex" in block.text
    assert "Babi (replying to Alex): always" in block.text
    assert "Now Dia (replying to Babi): count me in" in block.text
    assert block.truncated is False


def test_topic_context_cannot_include_other_topics_pending_questions_or_unknown_legacy_rows(env):
    from luna_core.room import record_inbound
    conn, reg = env
    for mid, uid, text, thread, parent in [
        ("1", ALEX, "ROOT_ONLY", "", None),
        ("2", ALEX, "TOPIC_55_QUESTION", "55", "3"),
        ("3", BABI, "OTHER_TOPIC_PRIVATE", "66", None),
        ("4", DIA, "OTHER_PENDING_QUESTION", "55", None),
        ("5", BABI, "SAME_TOPIC_BACKGROUND", "55", None),
    ]:
        record_inbound(conn, message_id=mid, chat_id=CHAT, user_id=uid, content=text,
                       thread_id=thread, reply_to_message_id=parent, timestamp=_iso(5))
    conn.execute("UPDATE messages SET thread_id=NULL WHERE message_id='1'")
    conn.commit()
    block = build_room_block(conn, CHAT, thread_id="55", current_message_id="2", registry=reg,
                             excluded_message_ids={"4"}, now=datetime(2026, 1, 1, 12, 10, tzinfo=timezone.utc))
    assert "TOPIC_55_QUESTION" in block.text and "SAME_TOPIC_BACKGROUND" in block.text
    for marker in ("ROOT_ONLY", "OTHER_TOPIC_PRIVATE", "OTHER_PENDING_QUESTION"):
        assert marker not in block.text
    assert [row["message_id"] for row in thread_chain(conn, "2", chat_id=CHAT, thread_id="55")] == ["2"]


def test_giant_roster_never_removes_the_current_request_before_background(env):
    from luna_core.room import RoomLine
    lines = [RoomLine(message_id=str(i), name="Very long display name " * 10, content="old", user_id=str(i), timestamp=None) for i in range(15)]
    lines.append(RoomLine(message_id="current", name="Alex", content="CURRENT_TARGET_QUESTION", user_id=ALEX, timestamp=None))
    block = render_block(lines, roster=[line.name + str(i) for i, line in enumerate(lines)],
                         current_message_id="current", max_chars=180, max_lines=20)
    assert "Now Alex: CURRENT_TARGET_QUESTION" in block.text
    assert block.chars <= 180 and block.truncated


def test_room_block_respects_line_and_char_caps(env):
    conn, reg = env
    for i in range(40):
        _add(conn, str(200 + i), ALEX, f"message number {i} " + "x" * 80, _iso(i))
    block = build_room_block(
        conn, CHAT, registry=reg, max_lines=10, max_chars=800,
        now=datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc),
    )
    assert block.lines <= 10
    assert block.chars <= 800
    assert block.truncated is True


def test_room_block_drops_oldest_first(env):
    conn, reg = env
    _add(conn, "1", ALEX, "oldest", _iso(0))
    _add(conn, "2", BABI, "middle", _iso(1))
    _add(conn, "3", DIA, "newest", _iso(2))
    block = build_room_block(
        conn, CHAT, registry=reg, max_lines=2,
        now=datetime(2026, 1, 1, 12, 3, tzinfo=timezone.utc),
    )
    assert "oldest" not in block.text
    assert "newest" in block.text


def test_reply_author_peer_id_from_explicit_author(env):
    conn, reg = env
    _add(conn, "101", ALEX, "hi", _iso(0))
    peer = reply_author_peer_id(
        conn, reply_to_message_id="101", reply_to_author_id=ALEX, registry=reg
    )
    assert peer == "alex"


def test_reply_author_peer_id_falls_back_to_index(env):
    conn, reg = env
    _add(conn, "101", ALEX, "hi", _iso(0))
    peer = reply_author_peer_id(conn, reply_to_message_id="101", registry=reg)
    assert peer == "alex"


def test_reply_author_peer_id_unknown_author_is_learned(env):
    conn, reg = env
    peer = reply_author_peer_id(conn, reply_to_author_id="9999", registry=reg)
    assert peer == "telegram_9999"


def test_render_block_marks_current_and_bounds():
    from luna_core.room import RoomLine

    lines = [
        RoomLine(message_id=str(i), user_id="1", name="Alex", content=f"c{i}",
                 timestamp=None, is_bot=False)
        for i in range(6)
    ]
    block = render_block(lines, current_message_id="5", max_lines=3, max_chars=1000)
    assert block.lines <= 3
    assert "Now Alex: c5" in block.text
    assert "c0" not in block.text


def test_room_block_keeps_reply_chain_when_over_caps(env):
    """Referents are protected: trimming costs chatter, never the thread that explains the turn."""
    from luna_core.room import TRUNCATION_NOTE, record_inbound

    conn, reg = env
    record_inbound(conn, message_id="root", chat_id=CHAT, user_id=ALEX, user_name="Alex",
                   content="the original question", timestamp=_iso(0))
    record_inbound(conn, message_id="mid", chat_id=CHAT, user_id=BABI, user_name="Babi",
                   content="the answer", reply_to_message_id="root", timestamp=_iso(1))
    for i in range(30):
        record_inbound(conn, message_id=str(200 + i), chat_id=CHAT, user_id=DIA, user_name="Dia",
                       content=f"chatter {i}", timestamp=_iso(2 + i % 20))
    record_inbound(conn, message_id="now", chat_id=CHAT, user_id=DIA, user_name="Dia",
                   content="count me in", reply_to_message_id="mid", timestamp=_iso(30))

    block = build_room_block(
        conn, CHAT, current_message_id="now", registry=reg, max_lines=6, max_chars=2000,
        now=datetime(2026, 1, 1, 12, 40, tzinfo=timezone.utc),
    )
    assert "the original question" in block.text
    assert "the answer" in block.text
    assert "Babi (replying to Alex)" in block.text
    assert "Now Dia (replying to Babi)" in block.text
    assert TRUNCATION_NOTE in block.text
    assert block.truncated is True


def test_room_block_truncation_marker_is_visible_and_bounded(env):
    from luna_core.room import TRUNCATION_NOTE

    conn, reg = env
    for i in range(20):
        _add(conn, str(10 + i), ALEX, "line " + "y" * 60, _iso(i))
    block = build_room_block(
        conn, CHAT, registry=reg, max_lines=3, max_chars=200,
        now=datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc),
    )
    assert block.truncated is True
    assert TRUNCATION_NOTE in block.text
    assert block.chars <= 200


def test_record_inbound_timestamps_default_to_now_and_stay_visible(env):
    """A triggered message without a clock must not vanish from the recent window."""
    from luna_core.room import recent_messages, record_inbound

    conn, _ = env
    record_inbound(conn, message_id="t1", chat_id=CHAT, user_id=ALEX, user_name="Alex",
                   content="no timestamp given")
    row = conn.execute("SELECT timestamp FROM messages WHERE message_id='t1'").fetchone()
    assert row["timestamp"]
    since = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
    assert [r["message_id"] for r in recent_messages(conn, CHAT, since_iso=since)] == ["t1"]


def test_duplicate_display_names_are_disambiguated(env):
    conn, reg = env
    reg.set_manual("telegram", "1111", peer_id="a1", display_name="Ali")
    reg.set_manual("telegram", "2222", peer_id="a2", display_name="Ali")
    _add(conn, "1", "1111", "first ali", _iso(0), name="Ali")
    _add(conn, "2", "2222", "second ali", _iso(1), name="Ali")
    block = build_room_block(conn, CHAT, registry=reg,
                             now=datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc))
    assert "Ali (…1111): first ali" in block.text
    assert "Ali (…2222): second ali" in block.text


def test_max_chars_is_hard_even_for_a_giant_roster():
    """A roster line alone can outgrow max_chars — the cap must not be advisory."""
    from luna_core.room import RoomLine, render_block

    names = [f"Member-With-A-Long-Name-{i}" for i in range(40)]
    lines = [
        RoomLine(message_id=str(i), user_id=str(i), name=names[i % len(names)], content="hi",
                 timestamp=None, is_bot=False)
        for i in range(10)
    ]
    block = render_block(lines, roster=names, max_lines=20, max_chars=150)
    assert block.chars <= 150
    assert block.truncated is True


def test_record_inbound_provenance_is_explicit(env):
    """observed/source must be per-caller: only real room chatter is observed=1/'live'."""
    from luna_core.room import record_inbound, record_luna_reply

    conn, _ = env
    record_inbound(conn, message_id="t1", chat_id=CHAT, user_id=ALEX, content="a live message")
    record_inbound(conn, message_id="s1", chat_id=CHAT, user_id=None, user_name="Luna",
                   content="quoted", is_bot=True, observed=False, source="stand-in")
    record_luna_reply(conn, message_id="luna:t:1", chat_id=CHAT, content="my reply")
    rows = {r["message_id"]: r for r in conn.execute(
        "SELECT message_id, observed, source FROM messages")}
    assert rows["t1"]["observed"] == 1 and rows["t1"]["source"] == "live"
    assert rows["s1"]["observed"] == 0 and rows["s1"]["source"] == "stand-in"
    assert rows["luna:t:1"]["observed"] == 0 and rows["luna:t:1"]["source"] == "reply"


def test_same_message_id_in_two_chats_never_collides():
    """Telegram message ids are per-chat; one chat's row must never overwrite another's."""
    import tempfile

    from luna_core.room import fetch_message, record_inbound

    with tempfile.TemporaryDirectory() as td:
        conn = db.connect(Path(td) / "luna-state.db")
        db.init_db(conn)
        record_inbound(conn, message_id="501", chat_id="-100", user_id=ALEX, content="chat A")
        record_inbound(conn, message_id="501", chat_id="-200", user_id=BABI, content="chat B")
        a = fetch_message(conn, "501", chat_id="-100")
        b = fetch_message(conn, "501", chat_id="-200")
        assert a["content"] == "chat A" and b["content"] == "chat B"
        conn.close()


def test_old_single_key_messages_migrate_in_place(tmp_path):
    """A pre-(chat_id, message_id) database is rebuilt without losing rows."""
    import sqlite3

    path = tmp_path / "luna-state.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE messages (
            message_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, user_id TEXT, user_name TEXT,
            peer_id TEXT, content TEXT, timestamp TEXT, reply_to_message_id TEXT,
            is_bot INTEGER NOT NULL DEFAULT 0, observed INTEGER NOT NULL DEFAULT 1,
            triggered INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'observe',
            indexed_at TEXT, embedding BLOB, embedding_dim INTEGER
        );
        INSERT INTO messages(message_id, chat_id, content) VALUES ('1', '-100', 'old row');
        """
    )
    old.commit()
    old.close()
    conn = db.connect(path)
    db.init_db(conn)  # triggers the rebuild
    row = conn.execute("SELECT content FROM messages WHERE message_id='1'").fetchone()
    assert row["content"] == "old row"
    pk = {r[1]: r[5] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
    assert pk.get("chat_id") and pk.get("message_id") > 1  # composite key
    conn.close()


@pytest.mark.parametrize("name", ["Mira", "Luna", "Companion"])
def test_own_reply_uses_the_persona_name_in_the_room(env, tmp_path, monkeypatch, name):
    from luna_core.room import record_luna_reply

    conn, reg = env
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "SOUL.md").write_text(f"# {name}\n\nA group companion.\n")
    _add(conn, "1", ALEX, f"hey {name}", _iso(0))
    record_luna_reply(conn, message_id="luna:s:1", chat_id=CHAT, content="hey — pizza again?",
                      timestamp=_iso(1))
    row = conn.execute("SELECT * FROM messages WHERE message_id='luna:s:1'").fetchone()
    assert row["is_bot"] == 1 and row["peer_id"] == "luna" and row["user_name"] == name
    block = build_room_block(conn, CHAT, registry=reg,
                             now=datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc))
    assert f"{name}: hey — pizza again?" in block.text
