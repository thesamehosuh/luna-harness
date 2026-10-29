"""Honcho store: peers, cards, the shared room session, and per-author writes."""

from __future__ import annotations

import pytest

from luna_core import db
from luna_core.honcho import HonchoStore, backfill_room, sanitize_session_id, sync_room_peers
from luna_core.identity import IdentityRegistry

CHAT = "-100"
ROOM = "luna-room"
OWNER, BABI = "1000000001", "1002"


def test_sanitize_session_id():
    # Honcho ids must match ^[a-zA-Z0-9_-]+$
    assert sanitize_session_id("agent:main:telegram:group:--1000000000000") == \
        "agent_main_telegram_group_--1000000000000"
    assert sanitize_session_id("luna-room") == "luna-room"
    assert sanitize_session_id("") == "room"


class FakeMessage:
    def __init__(self, content, metadata):
        self.content = content
        self.metadata = metadata


class FakePeer:
    def __init__(self, pid):
        self.pid = pid
        self.cards = []
        self.messages = []

    def set_card(self, card):
        self.cards = list(card)
        return self.cards

    def message(self, content, metadata=None, created_at=None):
        self.messages.append(content)
        return {"peer": self.pid, "content": content, "metadata": metadata}


class FakeSession:
    def __init__(self, sid, peers=None):
        self.sid = sid
        self.peers = list(peers or [])
        self.msgs = []

    def add_messages(self, messages):
        self.msgs.extend(messages)

    def messages(self):
        return [FakeMessage(m["content"], m.get("metadata")) for m in self.msgs]


class FakeHoncho:
    def __init__(self):
        self._peers = {}
        self._sessions = {}

    def peer(self, pid):
        return self._peers.setdefault(pid, FakePeer(pid))

    def session(self, sid, peers=None):
        s = self._sessions.get(sid)
        if s is None:
            s = FakeSession(sid, peers)
            self._sessions[sid] = s
        elif peers:
            s.peers = list(peers)
        return s


@pytest.fixture()
def env(tmp_path):
    conn = db.connect(tmp_path / "luna-state.db")
    db.init_db(conn)
    reg = IdentityRegistry(conn)
    reg.set_manual("telegram", OWNER, peer_id="sam", display_name="Sam", pronouns="he/him",
                   role="owner")
    reg.set_manual("telegram", BABI, peer_id="babi", display_name="Babi")

    rows = [
        ("m1", BABI, "babi", "anyone up for pizza?", "2026-01-01T12:00:00+00:00"),
        ("m2", OWNER, "sam", "always", "2026-01-01T12:05:00+00:00"),
        ("m3", "9999", None, "who is this", "2026-01-01T12:06:00+00:00"),  # unresolved author
    ]
    for mid, uid, peer, text, ts in rows:
        conn.execute(
            "INSERT INTO messages(message_id, chat_id, user_id, user_name, peer_id, content, "
            "timestamp, is_bot, observed) VALUES (?,?,?,?,?,?,?,0,1)",
            (mid, CHAT, uid, uid, peer, text, ts),
        )
    conn.commit()

    fake = FakeHoncho()
    store = HonchoStore(workspace="luna-test", client=fake)
    yield conn, reg, store, fake
    conn.close()


def test_ensure_peer_sets_card(env):
    _, _, store, fake = env
    store.ensure_peer("babi", ["name: Babi"])
    assert fake.peer("babi").cards == ["name: Babi"]


def test_sync_room_peers_creates_peers_cards_session(env):
    conn, reg, store, fake = env
    result = sync_room_peers(store, reg, room_session=ROOM)
    assert result.peers == 2
    assert result.cards == 2
    assert set(fake.session(ROOM).peers) == {"sam", "babi"}
    assert any("name: Sam" in f for f in fake.peer("sam").cards)


def test_backfill_writes_per_author(env):
    conn, reg, store, fake = env
    result = backfill_room(store, conn, chat_id=CHAT, room_session=ROOM, registry=reg)
    assert result.written == 2  # m1 (babi), m2 (sam); m3 has no resolvable peer
    assert result.skipped >= 1
    msgs = fake.session(ROOM).msgs
    assert {m["peer"] for m in msgs} == {"babi", "sam"}
    # the pizza message is authored by Babi, not by whoever spoke last
    assert any(m["peer"] == "babi" and "pizza" in m["content"] for m in msgs)


def test_backfill_is_idempotent(env):
    conn, reg, store, fake = env
    first = backfill_room(store, conn, chat_id=CHAT, room_session=ROOM, registry=reg)
    second = backfill_room(store, conn, chat_id=CHAT, room_session=ROOM, registry=reg)
    assert first.written == 2
    assert second.written == 0
    assert second.skipped == 0  # Delivered and unresolved-author work do not monopolize later batches.
    assert len(fake.session(ROOM).msgs) == 2


def test_backfill_includes_lunas_own_rows(env):
    """Luna's replies carry is_bot=1 — excluding them left a room where the AI never spoke."""
    conn, reg, store, fake = env
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, user_id, user_name, peer_id, content, "
        "timestamp, is_bot, observed) VALUES (?,?,?,?,?,?,?,1,1)",
        ("luna:t:1", CHAT, None, "Luna", "luna", "always, obviously",
         "2026-01-01T12:07:00+00:00"),
    )
    conn.commit()
    result = backfill_room(store, conn, chat_id=CHAT, room_session=ROOM, registry=reg)
    assert result.written == 3
    msgs = fake.session(ROOM).msgs
    assert any(m["peer"] == "luna" and "obviously" in m["content"] for m in msgs)


def test_topic_outboxes_never_copy_other_topics_into_their_sessions(env):
    conn, registry, store, fake = env
    conn.execute("UPDATE messages SET thread_id='9' WHERE message_id='m2'")
    conn.commit()
    main = backfill_room(store, conn, chat_id=CHAT, room_session='public-main', thread_id='', registry=registry)
    topic = backfill_room(store, conn, chat_id=CHAT, room_session='public-topic-9', thread_id='9', registry=registry)
    assert main.written == 1 and topic.written == 1
    assert [msg['content'] for msg in fake.session('public-main').msgs] == ['anyone up for pizza?']
    assert [msg['content'] for msg in fake.session('public-topic-9').msgs] == ['always']
