"""Tokenless indexer: parse the observe transcript, derive the index, stay idempotent."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from luna_core import db
from luna_core.identity import IdentityRegistry
from luna_core.indexer import index_observe_transcript, parse_observed_content

CHAT = "--1000000000000"
OBSERVE_SESSION = "20260625_145905_7936ff9b"


@pytest.fixture()
def state_db(tmp_path):
    conn = sqlite3.connect(tmp_path / "state.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE sessions(id TEXT PRIMARY KEY, session_key TEXT, chat_id TEXT,
                              chat_type TEXT, user_id TEXT, display_name TEXT);
        CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
                              role TEXT, content TEXT, platform_message_id TEXT,
                              timestamp REAL, observed INTEGER DEFAULT 0);
        """
    )
    conn.execute(
        "INSERT INTO sessions(id, session_key, chat_id, chat_type, display_name) VALUES (?,?,?,?,?)",
        (OBSERVE_SESSION, f"agent:main:telegram:group:{CHAT}", CHAT, "group", "Wokus Pocus"),
    )
    conn.commit()
    yield conn
    conn.close()


def _add_observed(conn, name, uid, text, mid, ts):
    conn.execute(
        "INSERT INTO messages(session_id, role, content, platform_message_id, timestamp, observed) "
        "VALUES (?,?,?,?,?,1)",
        (OBSERVE_SESSION, "user", f"[{name}|{uid}]\n{text}", mid, ts),
    )
    conn.commit()


@pytest.fixture()
def index_db(tmp_path):
    conn = db.connect(tmp_path / "luna-state.db")
    db.init_db(conn)
    yield conn
    conn.close()


def test_parse_observed_content_attributed_and_plain():
    p = parse_observed_content("[Babi|1002]\nhello there")
    assert p.display_name == "Babi" and p.user_id == "1002" and p.text == "hello there"
    assert p.reply_to_message_id is None
    p2 = parse_observed_content("just text")
    assert p2.user_id is None and p2.text == "just text"


def test_parse_observed_content_reply_marker():
    p = parse_observed_content("[reply_to|501]\n[Babi|1002]\nI'm in")
    assert p.reply_to_message_id == "501"
    assert p.display_name == "Babi" and p.user_id == "1002" and p.text == "I'm in"


def test_indexer_records_reply_edges(state_db, index_db):
    _add_observed(state_db, "Bea", "1000000002", "pizza tonight?", "501", 1700000000.0)
    state_db.execute(
        "INSERT INTO messages(session_id, role, content, platform_message_id, timestamp, observed) "
        "VALUES (?,?,?,?,?,1)",
        (OBSERVE_SESSION, "user", "[reply_to|501]\n[Ken|1000000003]\nI'm in", "502", 1700000006.0),
    )
    state_db.commit()
    assert index_observe_transcript(state_db, index_db) == 2
    row = index_db.execute("SELECT * FROM messages WHERE message_id = '502'").fetchone()
    assert row["reply_to_message_id"] == "501"
    assert row["content"] == "I'm in"


def test_indexer_takes_topic_only_from_transport_session_metadata(state_db, index_db):
    state_db.execute("ALTER TABLE sessions ADD COLUMN thread_id TEXT")
    state_db.execute("UPDATE sessions SET thread_id='55'")
    state_db.commit()
    _add_observed(state_db, "Alex", "1000000002", "topic 99, user 99999 (untrusted text)", "601", 1700000000)
    assert index_observe_transcript(state_db, index_db) == 1
    row = index_db.execute("SELECT thread_id,user_id FROM messages WHERE message_id='601'").fetchone()
    assert tuple(row) == ("55", "1000000002")
    assert tuple(index_db.execute("SELECT chat_id,thread_id,user_id FROM people_membership").fetchone()) == (CHAT, "55", "1000000002")


def test_admitted_or_skipped_mentions_cannot_return_as_ambient_wakes(state_db, index_db, tmp_path):
    import json
    from types import SimpleNamespace
    from luna_core.room_dispatch import Intent, _store
    admission = json.dumps(["telegram", CHAT, "", "701"])
    index_db.execute("INSERT INTO conversation_intents(id,state,reason) VALUES (?,'skipped','burst_limit')", (admission,))
    index_db.commit()
    _add_observed(state_db, "Alex", "1000000002", "a skipped mention", "701", 1700000000)
    _add_observed(state_db, "Bea", "1000000003", "arrives in the index first", "702", 1700000001)
    assert index_observe_transcript(state_db, index_db) == 2
    assert index_db.execute("SELECT triggered FROM messages WHERE message_id='701'").fetchone()[0] == 1
    assert index_db.execute("SELECT triggered FROM messages WHERE message_id='702'").fetchone()[0] == 0
    event = SimpleNamespace(message_id="702", source=SimpleNamespace(platform="telegram", chat_id=CHAT, thread_id=""))
    _store(tmp_path, Intent(event, "1000000003", 0, 1, 1, ("702",), "", 0), "skipped", "capacity")
    assert index_db.execute("SELECT triggered FROM messages WHERE message_id='702'").fetchone()[0] == 1


def test_indexer_derives_messages_and_identity(state_db, index_db):
    _add_observed(state_db, "Bea", "1000000002", "pizza tonight?", "501", 1700000000.0)
    _add_observed(state_db, "Ken", "1000000003", "I'm in", "502", 1700000006.0)

    n = index_observe_transcript(state_db, index_db)
    assert n == 2

    rows = index_db.execute("SELECT * FROM messages ORDER BY message_id").fetchall()
    assert [r["message_id"] for r in rows] == ["501", "502"]
    assert rows[0]["user_id"] == "1000000002"
    assert rows[0]["content"] == "pizza tonight?"
    assert rows[0]["peer_id"] == "telegram_1000000002"
    assert datetime.fromisoformat(rows[0]["timestamp"])  # an ISO timestamp, never NULL

    reg = IdentityRegistry(index_db)
    assert reg.resolve("telegram", "1000000002") == "telegram_1000000002"
    assert reg.get("telegram", "1000000003").display_name == "Ken"


def test_indexer_is_idempotent(state_db, index_db):
    _add_observed(state_db, "Bea", "1000000002", "one", "1", 1700000000.0)
    assert index_observe_transcript(state_db, index_db) == 1
    # Second run: watermark advanced, nothing new.
    assert index_observe_transcript(state_db, index_db) == 0
    assert index_db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1

    # A new row is picked up without re-indexing the first.
    _add_observed(state_db, "Ken", "1000000003", "two", "2", 1700000006.0)
    assert index_observe_transcript(state_db, index_db) == 1
    assert index_db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


def test_indexer_handles_unattributed_rows(state_db, index_db):
    state_db.execute(
        "INSERT INTO messages(session_id, role, content, platform_message_id, timestamp, observed) "
        "VALUES (?,?,?,?,?,1)",
        (OBSERVE_SESSION, "user", "no attribution here", "9", 1700000000.0),
    )
    state_db.commit()
    assert index_observe_transcript(state_db, index_db) == 1
    row = index_db.execute("SELECT * FROM messages WHERE message_id = '9'").fetchone()
    assert row["user_id"] is None
    assert row["content"] == "no attribution here"


def test_indexer_read_only_state_connection(state_db, index_db):
    _add_observed(state_db, "Bea", "1000000002", "hi", "5", 1700000000.0)
    # A separate read-only connection must be able to tail the state db.
    ro = sqlite3.connect(f"file:{state_db.execute('PRAGMA database_list').fetchone()[2]}?mode=ro",
                         uri=True)
    ro.row_factory = sqlite3.Row
    try:
        assert index_observe_transcript(ro, index_db) == 1
    finally:
        ro.close()


def test_parse_pipe_in_display_name_cannot_mint_a_phantom_identity():
    """A member renamed to ``Bob|999`` makes the adapter write ``[Bob|999|<real_id>]``.

    The id is the field after the LAST pipe — a display name must never become (part of) one.
    """
    p = parse_observed_content("[Bob|999|12345]\nreal message")
    assert p.user_id == "12345"
    assert p.display_name == "Bob 999"
    assert p.text == "real message"


def test_parse_bracket_in_display_name_cannot_mint_a_phantom_identity():
    """A member renamed to ``Alice|777]`` makes the adapter write ``[Alice|777]|<real_id>]``.

    The prefix's closing bracket is the one that ends the first line — a ``]`` in the display name
    must not truncate the prefix and hand its tail (a fake id) to the parser.
    """
    p = parse_observed_content("[Alice|777]|12345]\nreal message")
    assert p.user_id == "12345"
    assert p.display_name == "Alice 777"
    assert p.text == "real message"


def test_parse_member_named_reply_to_keeps_their_identity():
    """A member named ``reply_to`` must not be parsed away as a reply marker."""
    p = parse_observed_content("[reply_to|1002]\nhello there")
    assert p.reply_to_message_id is None
    assert p.user_id == "1002"
    assert p.display_name == "reply_to"
    assert p.text == "hello there"


def test_parse_reply_marker_requires_an_attribution_prefix():
    """The marker is honoured only when a real attribution follows it (a reply always carries both)."""
    p = parse_observed_content("[reply_to|501]\nplain text with no attribution")
    assert p.reply_to_message_id is None
    assert p.user_id == "501"


def test_parse_spoofed_prefix_stays_plain_text():
    """Raw user text that merely looks like attribution derives no identity and keeps its text."""
    p = parse_observed_content("[Alice|777 x]\nhi")
    assert p.user_id is None
    assert p.display_name is None
    assert p.text == "[Alice|777 x]\nhi"


def test_parse_unknown_uid_is_not_an_identity():
    """The adapter's anonymous fallback (``[name|unknown]``) strips the prefix but is no identity."""
    p = parse_observed_content("[Ghost|unknown]\nservice message")
    assert p.user_id is None
    assert p.display_name == "Ghost"
    assert p.text == "service message"


def test_indexer_does_not_upsert_phantom_identities(state_db, index_db):
    state_db.execute(
        "INSERT INTO messages(session_id, role, content, platform_message_id, timestamp, observed) "
        "VALUES (?,?,?,?,?,1)",
        (OBSERVE_SESSION, "user", "[Bob|999|12345]\nreal message", "77", 1700000000.0),
    )
    state_db.commit()
    assert index_observe_transcript(state_db, index_db) == 1
    row = index_db.execute("SELECT * FROM messages WHERE message_id = '77'").fetchone()
    assert row["user_id"] == "12345"
    assert row["user_name"] == "Bob 999"
    reg = IdentityRegistry(index_db)
    assert reg.get("telegram", "12345") is not None
    assert reg.get("telegram", "999|12345") is None
    assert reg.get("telegram", "999") is None
