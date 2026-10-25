"""Room + cross-session thread reconstruction.

Per-user sessions mean member B's reply lands in session B while member A's original message lives
only in session A. This module rebuilds "who said what, replying to whom" from the derived index so
``luna-room`` can stage a bounded block via the ephemeral sidecar.

It is pure logic over the sqlite index — no Telegram, no hermes. The plugin wrapper extracts
``reply_to_message_id`` (and, when available, ``reply_to_author_id``) from the inbound event and
passes them in.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from .identity import IdentityRegistry

DEFAULT_MAX_LINES = 20
DEFAULT_MAX_CHARS = 2000
DEFAULT_MAX_AGE_MINUTES = 360
DEFAULT_PER_LINE_CHARS = 220
DEFAULT_THREAD_DEPTH = 8

HEADER = "[Room context — recent messages]"
TRUNCATION_NOTE = "(…earlier room messages omitted)"
# Rows without a timestamp are recently-recorded (legacy live rows); treat them as newest so the
# ``since`` window and the line caps cannot silently drop them.
_TS_NULL_SENTINEL = "9999-12-31T23:59:59+00:00"


@dataclass
class RoomLine:
    message_id: str
    user_id: Optional[str]
    name: str
    content: str
    timestamp: Optional[str]
    reply_to_message_id: Optional[str] = None
    reply_to_name: Optional[str] = None
    is_bot: bool = False


@dataclass
class RoomBlock:
    text: str
    lines: int
    chars: int
    truncated: bool


def _display_name(
    user_id: Optional[str],
    user_name: Optional[str],
    registry: Optional[IdentityRegistry],
    platform: str,
) -> str:
    if user_id and registry is not None:
        ident = registry.get(platform, str(user_id))
        if ident and ident.display_name:
            return ident.display_name
    return user_name or (str(user_id) if user_id else "unknown")


def _truncate(text: str, limit: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def fetch_message(
    conn: sqlite3.Connection, message_id: str, *, chat_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> Optional[sqlite3.Row]:
    """Fetch one room-log row. ``chat_id`` scopes the lookup — Telegram message ids repeat across
    chats, so an unscoped fetch can return a different chat's row."""
    if chat_id is not None and thread_id is not None:
        return conn.execute("SELECT * FROM messages WHERE chat_id=? AND message_id=? AND thread_id=?", (str(chat_id), str(message_id), str(thread_id))).fetchone()
    if chat_id is not None:
        return conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? AND message_id = ?",
            (str(chat_id), str(message_id)),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM messages WHERE message_id = ?", (str(message_id),)
    ).fetchone()


def thread_chain(
    conn: sqlite3.Connection, message_id: str, *, max_depth: int = DEFAULT_THREAD_DEPTH,
    chat_id: Optional[str] = None, thread_id: Optional[str] = None,
) -> List[sqlite3.Row]:
    """Follow ``reply_to_message_id`` backwards, returning the chain oldest→newest."""
    chain: List[sqlite3.Row] = []
    seen = set()
    current = str(message_id)
    while current and current not in seen and len(chain) < max_depth:
        seen.add(current)
        row = fetch_message(conn, current, chat_id=chat_id, thread_id=thread_id)
        if row is None:
            break
        chain.append(row)
        current = row["reply_to_message_id"] or ""
        chat_id = row["chat_id"] or chat_id
    chain.reverse()
    return chain


def recent_messages(
    conn: sqlite3.Connection,
    chat_id: str,
    *,
    limit: int = DEFAULT_MAX_LINES,
    since_iso: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> List[sqlite3.Row]:
    # NULL timestamps are included: a triggered message recorded without a clock is still part of
    # the recent window (its referents matter more than its exact time).
    if thread_id is not None:
        age_clause = " AND (timestamp IS NULL OR timestamp >= ?)" if since_iso else ""
        params = [str(chat_id), str(thread_id), *([since_iso] if since_iso else []), _TS_NULL_SENTINEL, limit]
        rows = conn.execute("SELECT * FROM messages WHERE chat_id=? AND thread_id=?" + age_clause + " ORDER BY COALESCE(timestamp,?) DESC LIMIT ?", params).fetchall()
    elif since_iso:
        rows = conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? AND (timestamp IS NULL OR timestamp >= ?) "
            "ORDER BY COALESCE(timestamp, ?) DESC LIMIT ?",
            (str(chat_id), since_iso, _TS_NULL_SENTINEL, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? "
            "ORDER BY COALESCE(timestamp, ?) DESC LIMIT ?",
            (str(chat_id), _TS_NULL_SENTINEL, limit),
        ).fetchall()
    return list(reversed(rows))


def build_lines(
    conn: sqlite3.Connection,
    rows: Iterable[sqlite3.Row],
    *,
    registry: Optional[IdentityRegistry] = None,
    platform: str = "telegram",
    per_line_chars: int = DEFAULT_PER_LINE_CHARS,
) -> List[RoomLine]:
    """Render rows into :class:`RoomLine`s, resolving reply targets to author names."""
    lines: List[RoomLine] = []
    for row in rows:
        name = _display_name(row["user_id"], row["user_name"], registry, platform)
        reply_to = row["reply_to_message_id"]
        reply_name = None
        if reply_to:
            target = fetch_message(conn, reply_to, chat_id=row["chat_id"])
            if target is not None:
                reply_name = _display_name(target["user_id"], target["user_name"], registry, platform)
        lines.append(
            RoomLine(
                message_id=row["message_id"],
                user_id=row["user_id"],
                name=name,
                content=_truncate(row["content"], per_line_chars),
                timestamp=row["timestamp"],
                reply_to_message_id=reply_to,
                reply_to_name=reply_name,
                is_bot=bool(row["is_bot"]),
            )
        )
    return lines


def disambiguate_names(lines: List[RoomLine]) -> List[RoomLine]:
    """Make duplicate display names distinguishable (two members named "Ali" must not blur).

    A name held by more than one ``user_id`` gets a stable `` (…<last 4 of user id>)`` suffix.
    Purely mechanical — never infers identity, only decorates it.
    """
    by_name: Dict[str, set] = {}
    for line in lines:
        if line.user_id:
            by_name.setdefault(line.name, set()).add(str(line.user_id))
    dupes = {name for name, uids in by_name.items() if len(uids) > 1}
    if not dupes:
        return lines
    for line in lines:
        if line.name in dupes and line.user_id:
            uid = str(line.user_id)
            line.name = f"{line.name} (…{uid[-4:]})"
    return lines


def render_block(
    lines: List[RoomLine],
    *,
    roster: Optional[Iterable[str]] = None,
    current_message_id: Optional[str] = None,
    max_lines: int = DEFAULT_MAX_LINES,
    max_chars: int = DEFAULT_MAX_CHARS,
    pinned_ids: Optional[Iterable[str]] = None,
) -> RoomBlock:
    """Render a bounded room block.

    Caps are hard. Referents are protected: pinned lines (the reply chain + the current message)
    are dropped only after every unpinned line is gone, so trimming costs chatter, never the thread
    that makes the window interpretable. When anything was dropped, a visible marker is appended —
    silent loss is how a model ends up inventing the missing half.
    """
    roster_list = [r for r in dict.fromkeys(roster or []) if r]
    pinned = {str(p) for p in (pinned_ids or ()) if p}
    if current_message_id:
        pinned.add(str(current_message_id))

    parts: List[str] = [HEADER]
    if roster_list:
        parts.append("In the room: " + ", ".join(roster_list))

    # (rendered line, pinned, is_current)
    body: List[tuple] = []
    for line in lines:
        is_current = bool(current_message_id and line.message_id == current_message_id)
        prefix = "Now " if is_current else ""
        reply = f" (replying to {line.reply_to_name})" if line.reply_to_name else ""
        body.append((f"{prefix}{line.name}{reply}: {line.content}", str(line.message_id) in pinned, is_current))

    def _pop_oldest_movable() -> bool:
        for idx, (_text, is_pinned, _is_current) in enumerate(body):
            if not is_pinned:
                body.pop(idx)
                return True
        # Only pinned lines left: drop the oldest, but keep the current message while any other
        # line remains (it is the turn being answered).
        for idx, (_text, _is_pinned, is_current) in enumerate(body):
            if not (is_current and len(body) > 1):
                body.pop(idx)
                return True
        return False

    def _render(b: List[tuple], truncated: bool) -> str:
        texts = [t for t, _pinned, _current in b]
        if truncated:
            texts.append(TRUNCATION_NOTE)
        return "\n".join(parts + texts)

    truncated = False
    text = _render(body, truncated)
    while body and len(body) > max_lines:
        _pop_oldest_movable()
        truncated = True
        text = _render(body, truncated)
    # A long roster must not evict the request being answered. Drop that
    # redundant header before trimming message lines or the pinned reply chain.
    protected = [item for item in body if item[1]]
    if len(parts) > 1 and len(_render(protected or body[-1:], True)) > max_chars:
        parts = parts[:1]
        truncated = True
        text = _render(body, truncated)
    while body and len(text) > max_chars:
        _pop_oldest_movable()
        truncated = True
        text = _render(body, truncated)

    # The cap is hard: a roster line can outgrow max_chars on its own (a 15-member room with long
    # display names). Degrade the header side before anything else — chatter trimmed to nothing
    # plus a giant roster was the hole that made max_chars advisory.
    if len(text) > max_chars and len(parts) > 1:
        parts = parts[:1]
        truncated = True
        text = _render(body, truncated)
    if len(text) > max_chars:
        truncated = True
        text = text[:max_chars]

    return RoomBlock(
        text=text,
        lines=len(body),
        chars=len(text),
        truncated=truncated,
    )


def build_room_block(
    conn: sqlite3.Connection,
    chat_id: str,
    *,
    current_message_id: Optional[str] = None,
    registry: Optional[IdentityRegistry] = None,
    platform: str = "telegram",
    max_lines: int = DEFAULT_MAX_LINES,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
    per_line_chars: int = DEFAULT_PER_LINE_CHARS,
    thread_depth: int = DEFAULT_THREAD_DEPTH,
    now: Optional[datetime] = None,
    include_thread: bool = True,
    excluded_message_ids: Iterable[str] = (),
    thread_id: str = "",
) -> RoomBlock:
    """Build the bounded room/thread block for the current turn."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(minutes=max_age_minutes)).isoformat()

    rows = recent_messages(conn, chat_id, limit=max_lines, since_iso=since, thread_id=thread_id)
    excluded = set(excluded_message_ids) - {str(current_message_id)}
    rows = [row for row in rows if str(row["message_id"]) not in excluded]

    # Always include the current message even if it fell outside the window.
    ids = {r["message_id"] for r in rows}
    if current_message_id and current_message_id not in ids:
        cur = fetch_message(conn, current_message_id, chat_id=chat_id, thread_id=thread_id)
        if cur is not None:
            rows.append(cur)

    lines = build_lines(conn, rows, registry=registry, platform=platform,
                        per_line_chars=per_line_chars)

    # Prepend the explicit reply chain for the current message (the cross-session fix).
    pinned_ids = {str(current_message_id)} if current_message_id else set()
    if include_thread and current_message_id:
        chain = thread_chain(conn, current_message_id, max_depth=thread_depth, chat_id=chat_id, thread_id=thread_id)
        chain = [row for row in chain if str(row["message_id"]) not in excluded]
        if len(chain) > 1:
            chain_lines = build_lines(conn, chain[:-1], registry=registry, platform=platform,
                                      per_line_chars=per_line_chars)
            have = {l.message_id for l in chain_lines}
            pinned_ids |= {l.message_id for l in chain_lines}
            lines = chain_lines + [l for l in lines if l.message_id not in have]

    disambiguate_names(lines)
    roster = [l.name for l in lines if not l.is_bot]
    directory = ""
    if registry is not None and max_chars >= 900:
        from luna_core.people import context
        people_ids = [line.user_id for line in lines if line.message_id == current_message_id and line.user_id]
        people_ids += [line.user_id for line in reversed(lines) if line.user_id and not line.is_bot]
        directory = context(registry, platform, people_ids, chat_type="group", chat_id=chat_id, thread_id=thread_id, max_chars=min(640, max_chars // 3))
    block = render_block(
        lines,
        roster=roster,
        current_message_id=current_message_id,
        max_lines=max_lines,
        max_chars=max_chars - len(directory) - (2 if directory else 0),
        pinned_ids=pinned_ids,
    )
    if directory:
        block.text = directory + "\n\n" + block.text
        block.chars = len(block.text)
    return block


def reply_author_peer_id(
    conn: sqlite3.Connection,
    *,
    reply_to_message_id: Optional[str] = None,
    reply_to_author_id: Optional[str] = None,
    registry: Optional[IdentityRegistry] = None,
    platform: str = "telegram",
    chat_id: Optional[str] = None,
) -> Optional[str]:
    """Deterministically resolve the author of the replied-to message.

    Prefers an explicit transport author id (e.g. Telegram ``reply_to_message.from_user.id``,
    supplied by the adapter patch), then falls back to the index. Never infers from text.
    """
    if reply_to_author_id and registry is not None:
        peer = registry.resolve(platform, str(reply_to_author_id))
        if peer:
            return peer
        ident = registry.upsert_auto(platform, str(reply_to_author_id))
        return ident.peer_id
    if reply_to_message_id:
        row = fetch_message(conn, reply_to_message_id, chat_id=chat_id)
        if row and row["user_id"] and registry is not None:
            return registry.resolve(platform, str(row["user_id"])) or None
    return None


def reply_target_lookup(
    conn: sqlite3.Connection, message_id: str, *, chat_id: Optional[str] = None
) -> Optional[Dict[str, str]]:
    """Small helper for tests/plugins: ``{user_id, name, content}`` for a message id."""
    row = fetch_message(conn, message_id, chat_id=chat_id)
    if row is None:
        return None
    return {
        "message_id": row["message_id"],
        "user_id": row["user_id"],
        "name": row["user_name"] or "",
        "content": row["content"] or "",
    }


def record_inbound(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    chat_id: str,
    user_id: Optional[str],
    user_name: Optional[str] = None,
    content: str = "",
    reply_to_message_id: Optional[str] = None,
    peer_id: Optional[str] = None,
    timestamp: Optional[str] = None,
    is_bot: bool = False,
    observed: bool = True,
    source: str = "live",
    thread_id: str = "",
) -> None:
    """Upsert the current inbound message so the reply map stays live.

    Observe rows don't carry ``reply_to``; this is where the reply edges come from for the
    cross-session thread reconstruction. ``timestamp`` defaults to now: a NULL timestamp makes a
    row invisible to the recent-window query and to retention, which silently deleted triggered
    messages (and their referents) from every room block.

    Provenance (``observed``/``source``) is explicit per caller: ``observed=True/'live'`` for room
    messages seen at dispatch, ``observed=False/'stand-in'`` for a Luna quoted-message stub,
    ``observed=False/'reply'`` for her own replies. Blanket ``observed=1`` used to label every one
    of these as observed room chatter.
    """
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, thread_id, user_id, user_name, peer_id, content, timestamp, "
        "reply_to_message_id, is_bot, observed, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(chat_id, message_id) DO UPDATE SET "
        "  thread_id = excluded.thread_id, "
        "  reply_to_message_id = COALESCE(excluded.reply_to_message_id, messages.reply_to_message_id), "
        "  content = CASE WHEN excluded.content != '' THEN excluded.content ELSE messages.content END, "
        "  peer_id = COALESCE(excluded.peer_id, messages.peer_id), "
        "  timestamp = COALESCE(messages.timestamp, excluded.timestamp)",
        (
            str(message_id),
            str(chat_id),
            str(thread_id or ""),
            str(user_id) if user_id is not None else None,
            user_name,
            peer_id,
            content,
            timestamp or datetime.now(timezone.utc).isoformat(),
            str(reply_to_message_id) if reply_to_message_id is not None else None,
            1 if is_bot else 0,
            1 if observed else 0,
            str(source),
        ),
    )
    conn.commit()


def record_luna_reply(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    chat_id: str,
    content: str,
    timestamp: Optional[str] = None,
    thread_id: str = "",
) -> None:
    """Record one of this companion's group replies in the room log.

    Without these rows the room block never shows ``Luna: …``, reply chains that pass through her
    break silently, and the ambient wake-frequency gate always takes its "she never spoke" branch.
    """
    from .cascade import character_identity
    record_inbound(
        conn,
        message_id=message_id,
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=None,
        user_name=character_identity()[0],
        content=content,
        peer_id="luna",
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        is_bot=True,
        observed=False,
        source="reply",
    )
