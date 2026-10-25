"""Thin Honcho store — the room/identity write path.

We use the official ``honcho`` SDK directly (imported lazily) rather than vendoring the bundled
hermes provider, which is ~4k lines and tightly coupled to hermes internals. This module owns the
parts the plan needs:

- **Per-identity peers** — ``peer(id)`` from the transport id (never from text).
- **Peer cards** — name/pronouns/role facts so the deriver reasons about real people.
- **A shared room session with per-author writes** — every room message is written under its real
  author peer, so facts about X attach to X regardless of who Luna was addressing.

Note: Honcho **Scope** is not exposed in SDK 2.2.0 (only ``ConclusionScope`` types); room recall
uses the shared session plus peer representation instead. See the dashboard Help page's
Memory section.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .identity import IdentityRegistry

log = logging.getLogger("luna-honcho")

# Honcho session ids must match ^[a-zA-Z0-9_-]+$; our gateway session keys are colon-separated.
_SESSION_ID_BAD = re.compile(r"[^a-zA-Z0-9_-]+")


def sanitize_session_id(session_id: str) -> str:
    """Map a gateway session key to a valid Honcho session id.

    ``agent:main:telegram:group:-100…`` → ``agent_main_telegram_group_-100…``
    """
    cleaned = _SESSION_ID_BAD.sub("_", str(session_id or "")).strip("_")
    return cleaned or "room"


@dataclass
class RoomSyncResult:
    peers: int = 0
    cards: int = 0
    session: str = ""
    written: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)


class HonchoStore:
    """Small wrapper over the honcho SDK. ``client`` is injectable for tests."""

    def __init__(
        self,
        *,
        workspace: str = "luna",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 90.0,
        client: Any = None,
    ):
        self.workspace = workspace
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self._client = client

    def client(self) -> Any:
        if self._client is None:
            from honcho import Honcho  # lazy: only needed at runtime

            kwargs: Dict[str, Any] = {"workspace_id": self.workspace, "timeout": self.timeout}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            if self.api_key:
                kwargs["api_key"] = self.api_key
            self._client = Honcho(**kwargs)
        return self._client

    # -- peers ---------------------------------------------------------------
    def ensure_peer(self, peer_id: str, card: Optional[Sequence[str]] = None) -> Any:
        peer = self.client().peer(str(peer_id))
        if card:
            peer.set_card([str(f) for f in card])
        return peer

    def set_card(self, peer_id: str, facts: Sequence[str]) -> Any:
        return self.client().peer(str(peer_id)).set_card([str(f) for f in facts])

    # -- room session --------------------------------------------------------
    def ensure_room_session(self, session_id: str, peer_ids: Sequence[str]) -> Any:
        return self.client().session(sanitize_session_id(session_id),
                                     peers=[str(p) for p in peer_ids])

    def add_message(
        self,
        session_id: str,
        peer_id: str,
        content: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
    ) -> Any:
        """Write one message authored by ``peer_id`` into the shared room session."""
        peer = self.client().peer(str(peer_id))
        session = self.client().session(sanitize_session_id(session_id))
        message = peer.message(content, metadata=metadata, created_at=created_at)
        session.add_messages([message])
        return message

    def room_context(self, session_id: str, **kwargs: Any) -> Any:
        return self.client().session(sanitize_session_id(session_id)).context(**kwargs)


def connection_settings():
    """One profile-owned connection resolver for recall, room writes and health checks."""
    from luna_core import config_read
    from luna_core.runtime import home, getenv
    import json
    path = home() / "honcho.json"
    raw = json.loads(path.read_text()) if path.exists() else {}
    host = (raw.get("hosts") or {}).get("hermes") or {}
    cfg = config_read.section("honcho", default={}) or {}
    return {
        "workspace": getenv("LUNA_HONCHO_WORKSPACE") or cfg.get("workspace") or host.get("workspace") or raw.get("workspace") or "luna",
        "base_url": getenv("LUNA_HONCHO_BASE_URL") or cfg.get("baseUrl") or cfg.get("base_url") or host.get("baseUrl") or raw.get("baseUrl") or "http://localhost:8000",
        "api_key": getenv("HONCHO_API_KEY") or None,
        "timeout": float(getenv("LUNA_HONCHO_TIMEOUT") or cfg.get("timeout") or raw.get("timeout") or 30),
    }


def outbox_status(conn):
    try:
        row = conn.execute("SELECT COUNT(*), MIN(enqueued_at), SUM(state='uncertain'), SUM(attempts>0) FROM memory_outbox WHERE state!='delivered'").fetchone()
        return {"pending": row[0], "oldest_pending_at": row[1], "oldest_pending_age_seconds": max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(row[1])).total_seconds()) if row[1] else None, "uncertain": row[2] or 0, "failed": row[3] or 0}
    except sqlite3.OperationalError:
        return {"pending": 0, "oldest_pending_at": None, "uncertain": 0, "failed": 0}


# --------------------------------------------------------------------------- #
# room sync (registry -> Honcho)
# --------------------------------------------------------------------------- #
def _card_for(registry: IdentityRegistry, platform: str, user_id: str) -> List[str]:
    ident = registry.get(platform, user_id)
    if ident is None:
        return []
    facts: List[str] = []
    if ident.display_name:
        facts.append(f"name: {ident.display_name}")
    if ident.pronouns:
        facts.append(f"pronouns: {ident.pronouns}")
    if ident.role:
        facts.append(f"role: {ident.role}")
    if ident.aliases:
        facts.append("also known as: " + ", ".join(ident.aliases))
    return facts


def sync_room_peers(
    store: HonchoStore,
    registry: IdentityRegistry,
    *,
    platform: str = "telegram",
    room_session: str,
) -> RoomSyncResult:
    """Ensure every registered member is a peer with a card, and the shared room session exists."""
    result = RoomSyncResult(session=sanitize_session_id(room_session))
    peer_ids: List[str] = []
    for ident in registry.all_for_platform(platform):
        peer_ids.append(ident.peer_id)
        card = _card_for(registry, platform, ident.user_id)
        try:
            store.ensure_peer(ident.peer_id, card or None)
            result.peers += 1
            if card:
                result.cards += 1
        except Exception as exc:  # pragma: no cover - network
            result.errors.append(f"peer {ident.peer_id}: {exc}")
    if peer_ids:
        try:
            store.ensure_room_session(room_session, peer_ids)
        except Exception as exc:  # pragma: no cover - network
            result.errors.append(f"session {room_session}: {exc}")
    return result


def backfill_room(
    store: HonchoStore,
    conn: sqlite3.Connection,
    *,
    chat_id: str,
    room_session: str,
    platform: str = "telegram",
    limit: int = 500,
    registry: Optional[IdentityRegistry] = None,
    now: Optional[datetime] = None,
) -> RoomSyncResult:
    """Drain oldest-first durable work, including quiet-room retries.

    Remote enumeration must succeed before any send. A send with an unknown outcome is held
    for reconciliation; blindly replaying it cannot be made idempotent with Honcho's API.
    """
    import hashlib
    registry = registry or IdentityRegistry(conn)
    result = RoomSyncResult(session=sanitize_session_id(room_session))
    destination = hashlib.sha256(f"{store.base_url}|{store.workspace}|{result.session}".encode()).hexdigest()
    at = (now or datetime.now(timezone.utc)).isoformat()
    conn.execute("""INSERT OR IGNORE INTO memory_outbox(destination, chat_id, message_id, enqueued_at)
        SELECT ?, chat_id, message_id, ? FROM messages WHERE chat_id=? AND (is_bot=0 OR peer_id='luna')""", (destination, at, str(chat_id)))
    conn.commit()
    from luna_core.db import get_meta, set_meta
    retry_key = "memory_retry:" + destination
    retry_at = float(get_meta(conn, retry_key) or 0)
    if (now or datetime.now(timezone.utc)).timestamp() < retry_at:
        return result
    # Unknown authors cannot monopolize a batch forever. Retry them after identity is learned.
    conn.execute("""UPDATE memory_outbox SET state='pending' WHERE state='identity_wait' AND EXISTS
        (SELECT 1 FROM messages m JOIN identity i ON i.user_id=m.user_id
         WHERE m.chat_id=memory_outbox.chat_id AND m.message_id=memory_outbox.message_id)""")
    conn.commit()
    rows = conn.execute("""SELECT m.*, o.state AS delivery_state, o.attempts AS delivery_attempts FROM memory_outbox o JOIN messages m
        ON m.chat_id=o.chat_id AND m.message_id=o.message_id
        WHERE o.destination=? AND o.chat_id=? AND o.state IN ('pending','uncertain')
        ORDER BY (o.state='pending') DESC, m.timestamp, m.message_id LIMIT ?""", (destination, str(chat_id), max(1, limit))).fetchall()
    if not rows:
        return result
    initialized_key = "memory_reconciled:" + destination
    initial = not get_meta(conn, initialized_key)
    needs_lookup = initial or any(row["delivery_state"] == "uncertain" or row["delivery_attempts"] for row in rows)
    try:
        existing = set()
        for message in store.client().session(result.session).messages() if needs_lookup else ():
            meta = getattr(message, "metadata", None) or {}
            if meta.get("message_id") is not None and (not meta.get("chat_id") or str(meta["chat_id"]) == str(chat_id)):
                existing.add(str(meta["message_id"]))
        if initial:
            for mid in existing:
                conn.execute("UPDATE memory_outbox SET state='delivered', last_error=NULL WHERE destination=? AND chat_id=? AND message_id=?", (destination, str(chat_id), mid))
            conn.commit()
            set_meta(conn, initialized_key, "1")
    except Exception:
        conn.execute("UPDATE memory_outbox SET attempts=attempts+1, last_error='remote_lookup_failed' WHERE destination=? AND state!='delivered'", (destination,))
        conn.commit()
        attempts = conn.execute("SELECT MAX(attempts) FROM memory_outbox WHERE destination=?", (destination,)).fetchone()[0] or 1
        set_meta(conn, retry_key, str((now or datetime.now(timezone.utc)).timestamp() + min(300, 5 * 2 ** min(attempts, 6))))
        result.errors.append("Remote reconciliation unavailable; delivery deferred")
        return result
    for row in rows:
        mid = str(row["message_id"])
        key = (destination, str(chat_id), mid)
        if mid in existing:
            conn.execute("UPDATE memory_outbox SET state='delivered', last_error=NULL WHERE destination=? AND chat_id=? AND message_id=?", key)
            conn.commit()
            result.skipped += 1
            continue
        if row["delivery_state"] == "uncertain":
            result.errors.append("A delivery has an uncertain outcome and needs reconciliation")
            continue
        peer_id = row["peer_id"] or (registry.resolve(platform, str(row["user_id"])) if row["user_id"] else None)
        if not peer_id:
            conn.execute("UPDATE memory_outbox SET state='identity_wait', last_error='unknown_transport_author' WHERE destination=? AND chat_id=? AND message_id=?", key)
            conn.commit()
            result.skipped += 1
            continue
        # Commit the uncertain marker BEFORE the side effect, including process-crash windows.
        claimed = conn.execute("UPDATE memory_outbox SET state='uncertain', attempts=attempts+1, last_error='send_unconfirmed' WHERE destination=? AND chat_id=? AND message_id=? AND state='pending'", key)
        conn.commit()
        if claimed.rowcount != 1:
            continue
        try:
            created = datetime.fromisoformat(row["timestamp"]) if row["timestamp"] else None
            store.add_message(room_session, peer_id, row["content"] or "", metadata={"message_id": mid, "chat_id": str(chat_id), "source": "room-outbox"}, created_at=created)
            conn.execute("UPDATE memory_outbox SET state='delivered', last_error=NULL WHERE destination=? AND chat_id=? AND message_id=?", key)
            conn.commit()
            result.written += 1
        except Exception:
            result.errors.append("Delivery outcome unknown; held for reconciliation")
    return result
