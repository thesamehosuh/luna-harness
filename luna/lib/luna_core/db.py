"""SQLite store for the derived Luna index (``luna-state.db``).

The raw room log is the gateway's observe transcript in ``state.db``. ``luna-state.db`` is a
*derived, rebuildable* index built by ``luna-logger`` from that transcript, plus the identity
registry, wake ledger, and cross-surface digests.

Nothing here talks to the network or to hermes; it is pure sqlite.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_intents (
    id TEXT PRIMARY KEY, platform TEXT, chat_id TEXT, thread_id TEXT,
    user_id TEXT, message_id TEXT, state TEXT, reason TEXT, at REAL,
    expires REAL, pid INTEGER, process_start REAL, anchor_message_id TEXT
);

CREATE TABLE IF NOT EXISTS memory_outbox (
    destination TEXT NOT NULL, chat_id TEXT NOT NULL, message_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending', enqueued_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
    PRIMARY KEY(destination, chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_outbox_state ON memory_outbox(state, enqueued_at);

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Derived room log: one row per observed room message.
-- Keyed by (chat_id, message_id): Telegram message ids are per-chat and repeat across chats, so a
-- bare message_id key silently overwrote one chat's row with another's.
CREATE TABLE IF NOT EXISTS messages (
    message_id          TEXT NOT NULL,
    chat_id             TEXT NOT NULL,
    thread_id           TEXT DEFAULT '',
    user_id             TEXT,
    user_name           TEXT,
    peer_id             TEXT,
    content             TEXT,
    timestamp           TEXT,
    reply_to_message_id TEXT,
    is_bot              INTEGER NOT NULL DEFAULT 0,
    observed            INTEGER NOT NULL DEFAULT 1,
    triggered           INTEGER NOT NULL DEFAULT 0,  -- handled reactively by the gateway
    source              TEXT NOT NULL DEFAULT 'observe',
    indexed_at          TEXT,
    embedding           BLOB,
    embedding_dim       INTEGER,
    PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_ts  ON messages(chat_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_user     ON messages(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_messages_reply_to ON messages(reply_to_message_id);

CREATE TABLE IF NOT EXISTS people_membership (
    platform TEXT NOT NULL, chat_id TEXT NOT NULL, thread_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL, PRIMARY KEY(platform, chat_id, thread_id, user_id)
);

-- Identity registry: the single source of truth for peer attribution.
CREATE TABLE IF NOT EXISTS identity (
    platform    TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    user_id_alt TEXT,
    peer_id     TEXT NOT NULL,
    display_name TEXT,
    pronouns    TEXT,
    aliases     TEXT,          -- JSON array of strings
    role        TEXT,
    is_manual   INTEGER NOT NULL DEFAULT 0,
    first_seen  TEXT,
    updated_at  TEXT,
    PRIMARY KEY (platform, user_id)
);
CREATE INDEX IF NOT EXISTS idx_identity_peer ON identity(peer_id);

-- Wake ledger: hard rarity budget, independent of jev.
CREATE TABLE IF NOT EXISTS wakes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                TEXT NOT NULL,          -- 'message' | 'reaction'
    chat_id             TEXT NOT NULL,
    trigger_message_id  TEXT,
    created_at          TEXT NOT NULL,
    detail              TEXT                    -- JSON
);
CREATE INDEX IF NOT EXISTS idx_wakes_kind_ts ON wakes(kind, created_at);

-- What jev actually cost. OpenRouter reports a per-call `usage.cost` in USD, which is far more
-- trustworthy than estimating from characters, so the paid fallback is metered rather than guessed.
CREATE TABLE IF NOT EXISTS jev_usage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT NOT NULL,
    route               TEXT NOT NULL,          -- 'primary' | 'fallback:<provider>'
    provider            TEXT,
    requested_model     TEXT,
    served_model        TEXT,
    request_id          TEXT,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    cost_usd            REAL,
    trigger_message_id  TEXT,
    action              TEXT                    -- what the cascade decided with it
);
CREATE INDEX IF NOT EXISTS idx_jev_usage_created ON jev_usage(created_at);

CREATE TABLE IF NOT EXISTS ambient_intents (
    id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, thread_id TEXT NOT NULL, message_id TEXT NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL
);

-- Bounded score snapshots for genuinely offline threshold replay (no room transcript).
CREATE TABLE IF NOT EXISTS ambient_judgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL, thread_id TEXT NOT NULL DEFAULT '', message_id TEXT NOT NULL,
    created_at TEXT NOT NULL, answers TEXT NOT NULL, original_action TEXT NOT NULL,
    candidate_text TEXT NOT NULL DEFAULT '', revision TEXT NOT NULL DEFAULT ''
);

-- Cross-surface digests (group / dm / cli).
CREATE TABLE IF NOT EXISTS digests (
    surface    TEXT PRIMARY KEY,
    content    TEXT,
    updated_at TEXT
);

-- Generic key/value meta (indexer watermark, schema version, ...).
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _restrict_permissions(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            os.chmod(candidate, 0o600)
        except FileNotFoundError:
            continue
        except OSError:
            continue


def connect(path: str | Path, *, read_only: bool = False, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open ``luna-state.db`` with sane defaults.

    WAL is enabled for the writer so readers never block; read-only callers open with ``mode=ro``
    and never create the file. Pass ``check_same_thread=False`` for connections used across threads
    (e.g. the memory provider, which the manager may call from several threads).
    """
    path = Path(path)
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not read_only and str(path) != ":memory:":
        _restrict_permissions(path)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema if missing, apply lightweight migrations, and stamp the version."""
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    database_row = conn.execute("PRAGMA database_list").fetchone()
    database_path = str(database_row[2] or "") if database_row else ""
    if database_path and database_path != ":memory:":
        _restrict_permissions(Path(database_path))


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first schema without dropping data."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "triggered" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN triggered INTEGER NOT NULL DEFAULT 0")
    if "source" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN source TEXT NOT NULL DEFAULT 'observe'")
    # Rebuild messages keyed by (chat_id, message_id): Telegram message ids are per-chat and
    # repeat across chats. Old single-column-PK databases migrate in place; the table is derived
    # and its rows are preserved verbatim.
    pk_cols = {
        row[1]: row[5]
        for row in conn.execute("PRAGMA table_info(messages)").fetchall()
    }
    if pk_cols.get("message_id") == 1 and not pk_cols.get("chat_id"):
        conn.execute(
            "CREATE TABLE messages_migrated ("
            " message_id TEXT NOT NULL, chat_id TEXT NOT NULL, user_id TEXT, user_name TEXT,"
            " peer_id TEXT, content TEXT, timestamp TEXT, reply_to_message_id TEXT,"
            " is_bot INTEGER NOT NULL DEFAULT 0, observed INTEGER NOT NULL DEFAULT 1,"
            " triggered INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'observe',"
            " indexed_at TEXT, embedding BLOB, embedding_dim INTEGER,"
            " PRIMARY KEY (chat_id, message_id))"
        )
        conn.execute(
            "INSERT INTO messages_migrated (message_id, chat_id, user_id, user_name, peer_id,"
            " content, timestamp, reply_to_message_id, is_bot, observed, triggered, source,"
            " indexed_at, embedding, embedding_dim) "
            "SELECT message_id, chat_id, user_id, user_name, peer_id, content, timestamp,"
            " reply_to_message_id, is_bot, observed, triggered, source, indexed_at, embedding,"
            " embedding_dim FROM messages"
        )
        if "thread_id" in cols:
            conn.execute("ALTER TABLE messages_migrated ADD COLUMN thread_id TEXT")
            conn.execute("UPDATE messages_migrated SET thread_id=(SELECT thread_id FROM messages WHERE messages.message_id=messages_migrated.message_id)")
        conn.execute("DROP TABLE messages")
        conn.execute("ALTER TABLE messages_migrated RENAME TO messages")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_ts  ON messages(chat_id, timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_user     ON messages(chat_id, user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_reply_to ON messages(reply_to_message_id)")
        conn.commit()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    if "thread_id" not in cols:
        # Unknown legacy topic metadata stays unknown; never guess a topic from text.
        conn.execute("ALTER TABLE messages ADD COLUMN thread_id TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_thread_ts ON messages(chat_id,thread_id,timestamp)")
    member_cols = {row[1] for row in conn.execute("PRAGMA table_info(people_membership)")}
    if "thread_id" not in member_cols:
        conn.execute("CREATE TABLE people_membership_new (platform TEXT NOT NULL, chat_id TEXT NOT NULL, thread_id TEXT NOT NULL DEFAULT '', user_id TEXT NOT NULL, PRIMARY KEY(platform,chat_id,thread_id,user_id))")
        conn.execute("INSERT OR IGNORE INTO people_membership_new SELECT platform,chat_id,'',user_id FROM people_membership")
        conn.execute("DROP TABLE people_membership")
        conn.execute("ALTER TABLE people_membership_new RENAME TO people_membership")
    from .identity import heal_identity_platform_keys

    heal_identity_platform_keys(conn)


def mark_triggered(conn: sqlite3.Connection, message_id: str, chat_id: Optional[str] = None) -> None:
    """Mark a message as handled reactively by the gateway so the ambient layer skips it."""
    if chat_id is not None:
        conn.execute(
            "UPDATE messages SET triggered = 1 WHERE chat_id = ? AND message_id = ?",
            (str(chat_id), str(message_id)),
        )
    else:
        conn.execute(
            "UPDATE messages SET triggered = 1 WHERE message_id = ?", (str(message_id),)
        )
    conn.commit()


@contextmanager
def open_db(path: str | Path, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Context manager that opens, yields, and closes a connection."""
    conn = connect(path, read_only=read_only)
    try:
        if not read_only:
            init_db(conn)
        yield conn
    finally:
        conn.close()


def get_meta(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def record_jev_usage(conn: sqlite3.Connection, *, route: str, usage: Optional[dict] = None,
                     requested_model: Optional[str] = None, trigger_message_id: Optional[str] = None,
                     action: Optional[str] = None, created_at: Optional[str] = None) -> None:
    """Persist one jev call's reported usage/cost (best-effort; never breaks a decision)."""
    if usage is None:
        return
    cost = usage.get("cost")
    try:
        conn.execute(
            "INSERT INTO jev_usage(created_at, route, provider, requested_model, served_model, "
            "request_id, input_tokens, output_tokens, cost_usd, trigger_message_id, action) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                created_at or datetime.now(timezone.utc).isoformat(),
                route,
                usage.get("provider"),
                requested_model,
                usage.get("served_model"),
                usage.get("request_id"),
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                float(cost) if isinstance(cost, (int, float)) else None,
                trigger_message_id,
                action,
            ),
        )
        conn.commit()
    except Exception:
        pass


def jev_spend(conn: sqlite3.Connection, since_iso: Optional[str] = None) -> dict:
    """Total jev spend, optionally since an ISO timestamp. Reads a read-only connection fine."""
    where = "WHERE created_at >= ?" if since_iso else ""
    params: tuple = (since_iso,) if since_iso else ()
    row = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(cost_usd), 0.0) total, "
        f"COALESCE(SUM(input_tokens), 0) tokens, SUM(cost_usd IS NULL) unknown FROM jev_usage {where}",
        params,
    ).fetchone()
    by_route = conn.execute(
        f"SELECT route, COUNT(*) n, COALESCE(SUM(cost_usd), 0.0) total FROM jev_usage {where} "
        f"GROUP BY route ORDER BY total DESC",
        params,
    ).fetchall()
    return {
        "calls": row["n"],
        "total_usd": row["total"],
        "input_tokens": row["tokens"],
        "unknown_cost_calls": row["unknown"] or 0,
        "by_route": [{"route": r["route"], "calls": r["n"], "usd": r["total"]} for r in by_route],
    }
