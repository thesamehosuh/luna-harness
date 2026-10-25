"""Tokenless indexer: tail the gateway's observe transcript into ``luna-state.db``.

The gateway is the sole Telegram poller. With ``observe_unmentioned_group_messages`` enabled it
writes skipped group chatter into a *shared* observe session in ``state.db``. This module reads
those rows (read-only) and derives the index.

Observed row shape (verified against the live install):

- ``messages.observed = 1``, ``messages.role = 'user'``
- ``messages.content`` = ``"[<display_name>|<user_id>]\\n<text>"``, optionally preceded by a
  ``"[reply_to|<transport_message_id>]\\n"`` line for replies (patch 0006 — the transcript has no
  reply column, so the edge rides in-band and is parsed back here)
- ``messages.platform_message_id`` = the transport message id
- ``messages.timestamp`` = epoch seconds (REAL)
- the shared observe session's ``session_key`` has **no** per-user suffix
  (e.g. ``agent:main:telegram:group:<chat>``), so it never merges the per-user dispatch sessions.

The identity is parsed from the ``[name|id]`` prefix — never inferred from the message text. The
prefix is adapter-written, but display names are attacker-controlled, so the parser is strict: the
user id is the *last* ``|``-separated field (a name containing ``|`` cannot mint a phantom id), it
must look like an id, and anything that fails validation stays plain text — never identity.
"""

from __future__ import annotations

import re
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .identity import IdentityRegistry
from .text import strip_media_placeholders

# The prefix's closing bracket is the first ``]`` that ends the first line: the adapter writes
# ``[{name}|{uid}]\n{text}`` and display names cannot contain newlines. Anchoring on ``\n``/EOS
# (not on the first ``]``) is what stops a display name containing ``]`` from truncating the prefix
# and minting a phantom identity out of the name's tail.
ATTRIBUTION_RE = re.compile(
    r"^\[(?P<inner>[^\n]*)\](?=\n|$)\s*\n?(?P<text>.*)$", re.DOTALL
)
# Optional in-band reply marker the Telegram adapter prepends to observed replies (patch 0006):
# ``[reply_to|<transport_message_id>]\n``. The transcript has no reply column.
REPLY_MARKER_RE = re.compile(r"^\[reply_to\|(?P<rid>[^\]]+)\]\s*\n")
# Transport ids never contain spaces, brackets, or pipes. Anything else in the id slot is user
# text that merely *looks* like an attribution prefix (or a display name injection).
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

OBSERVE_WATERMARK_KEY = "observe_row_watermark"
DEFAULT_BATCH = 500


@dataclass
class ParsedObserved:
    display_name: Optional[str]
    user_id: Optional[str]
    text: str
    reply_to_message_id: Optional[str] = None


def _clean_display_name(name: str) -> Optional[str]:
    cleaned = re.sub(r"[\[\]|]", " ", name or "")
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned or None


def _has_attribution_prefix(text: str) -> bool:
    """True when ``text`` starts with a well-formed ``[name|uid]`` attribution prefix."""
    match = ATTRIBUTION_RE.match(text)
    if not match:
        return False
    inner = match.group("inner") or ""
    if "|" not in inner:
        return False
    uid = inner.rsplit("|", 1)[1].strip()
    return uid == "unknown" or bool(SAFE_ID_RE.match(uid))


def parse_observed_content(content: str) -> ParsedObserved:
    """Parse ``[name|user_id]\\ntext``, with an optional leading ``[reply_to|<id>]`` marker.

    Deterministic rules, in order:

    - the user id is everything after the **last** ``|`` inside the brackets (adapter format is
      ``[{name}|{uid}]``; a display name containing ``|`` therefore cannot shift the id);
    - the prefix's closing bracket is the first ``]`` that ends the first line (display names
      cannot contain newlines, so a name containing ``]`` cannot truncate the prefix and hand its
      tail — a fake id — to the parser);
    - the id must match :data:`SAFE_ID_RE`; ``unknown`` (the adapter's anonymous fallback) is not
      an identity;
    - the ``[reply_to|<id>]`` marker is honoured only when a real attribution prefix follows it
      (a reply always carries both). A member *named* ``reply_to`` therefore keeps their identity
      instead of being parsed away as a marker;
    - anything failing the above is **plain user text** — the prefix is kept, no identity is
      derived, and nothing is upserted.
    """
    original = content or ""
    text = original
    reply_to = None
    marker = REPLY_MARKER_RE.match(text)
    if marker and SAFE_ID_RE.match((marker.group("rid") or "").strip()):
        rest = text[marker.end():]
        if _has_attribution_prefix(rest):
            reply_to = (marker.group("rid") or "").strip() or None
            text = rest
    match = ATTRIBUTION_RE.match(text)
    if not match:
        return ParsedObserved(display_name=None, user_id=None, text=text.strip(),
                              reply_to_message_id=reply_to)
    inner = match.group("inner") or ""
    if "|" not in inner:
        return ParsedObserved(display_name=None, user_id=None, text=text.strip(),
                              reply_to_message_id=reply_to)
    name, uid = inner.rsplit("|", 1)
    uid = uid.strip()
    if uid == "unknown":
        # The adapter's anonymous fallback: strip the prefix, keep the name, derive no identity.
        return ParsedObserved(
            display_name=_clean_display_name(name),
            user_id=None,
            text=(match.group("text") or "").strip(),
            reply_to_message_id=reply_to,
        )
    if not SAFE_ID_RE.match(uid):
        # Not a trustworthy attribution prefix: keep the whole thing as the user's text.
        return ParsedObserved(display_name=None, user_id=None, text=text.strip(),
                              reply_to_message_id=reply_to)
    return ParsedObserved(
        display_name=_clean_display_name(name),
        user_id=uid,
        text=(match.group("text") or "").strip(),
        reply_to_message_id=reply_to,
    )


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def _observed_rows(state_conn: sqlite3.Connection, after_id: int, limit: int) -> list:
    columns = {row[1] for row in state_conn.execute("PRAGMA table_info(sessions)")}
    topic = "s.thread_id" if "thread_id" in columns else "NULL"
    return state_conn.execute(
        "SELECT m.id AS row_id, m.session_id, m.content, m.platform_message_id, m.timestamp, "
        f"       s.chat_id AS chat_id, s.chat_type AS chat_type, s.session_key AS session_key, {topic} AS thread_id "
        "FROM messages m LEFT JOIN sessions s ON s.id = m.session_id "
        "WHERE m.observed = 1 AND m.role = 'user' AND m.id > ? "
        "ORDER BY m.id ASC LIMIT ?",
        (after_id, limit),
    ).fetchall()


def index_observe_transcript(
    state_conn: sqlite3.Connection,
    index_conn: sqlite3.Connection,
    *,
    registry: Optional[IdentityRegistry] = None,
    platform: str = "telegram",
    batch: int = DEFAULT_BATCH,
    now: Optional[str] = None,
    max_batches: int = 1000,
) -> int:
    """Index new observed rows. Returns the number of rows indexed.

    Idempotent: the ``messages.id`` watermark advances, so re-runs never duplicate.
    """
    from . import db as _db

    registry = registry or IdentityRegistry(index_conn)
    watermark = int(_db.get_meta(index_conn, OBSERVE_WATERMARK_KEY, "0") or "0")
    total = 0

    for _ in range(max_batches):
        rows = _observed_rows(state_conn, watermark, batch)
        if not rows:
            break
        for row in rows:
            watermark = max(watermark, int(row["row_id"]))
            parsed = parse_observed_content(row["content"])
            chat_id = row["chat_id"] or row["session_id"]
            peer_id = None
            if parsed.user_id:
                ident = registry.upsert_auto(
                    platform, parsed.user_id, display_name=parsed.display_name, now=now
                )
                peer_id = ident.peer_id
                # Preserve transport-observed membership after transcript retention.
                # File/model edits cannot create this evidence or cross topic scopes.
                index_conn.execute("INSERT OR IGNORE INTO people_membership(platform,chat_id,thread_id,user_id) VALUES (?,?,?,?)",
                                   (ident.platform, str(chat_id), str(row["thread_id"] or ""), ident.user_id))
            message_id = row["platform_message_id"] or f"{row['session_id']}:{row['row_id']}"
            # Media placeholders carry a ``/.luna/cache/…`` host path; indexed verbatim it reads as
            # a mention of Luna and wakes her on a meme. Keep any caption, drop the machinery.
            stored_text = strip_media_placeholders(parsed.text)
            # The gateway can admit/skip a mention before this tokenless indexer
            # sees it. Such messages must not return later as ambient wake targets.
            admission_id = json.dumps([platform, str(chat_id), str(row["thread_id"] or ""), str(message_id)])
            index_conn.execute(
                "INSERT INTO messages(message_id, chat_id, thread_id, user_id, user_name, peer_id, content, "
                "timestamp, reply_to_message_id, is_bot, observed, triggered, source, indexed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,0,1,EXISTS(SELECT 1 FROM conversation_intents WHERE id=?),'observe',?) "
                "ON CONFLICT(chat_id, message_id) DO UPDATE SET "
                "  thread_id = excluded.thread_id, "
                "  content = excluded.content, user_id = excluded.user_id, "
                "  triggered = MAX(messages.triggered, excluded.triggered), "
                "  user_name = excluded.user_name, peer_id = excluded.peer_id, "
                "  reply_to_message_id = COALESCE(excluded.reply_to_message_id, "
                "                                messages.reply_to_message_id)",
                (
                    str(message_id),
                    str(chat_id),
                    str(row["thread_id"] or ""),
                    parsed.user_id,
                    parsed.display_name,
                    peer_id,
                    stored_text,
                    _iso(row["timestamp"]),
                    parsed.reply_to_message_id,
                    admission_id,
                    now,
                ),
            )
            total += 1
        _db.set_meta(index_conn, OBSERVE_WATERMARK_KEY, str(watermark))
        if len(rows) < batch:
            break

    index_conn.commit()
    return total
