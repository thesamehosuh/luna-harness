from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from luna.tools import prune_data


def test_prune_luna_db_removes_only_aged_rows(tmp_path):
    """Against the REAL schema (the pruner once targeted columns that do not exist)."""
    from luna_core import db

    path = tmp_path / "luna-state.db"
    conn = db.connect(path)
    db.init_db(conn)
    old = "2025-12-31T00:00:00+00:00"
    new = "2026-01-03T00:00:00+00:00"
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, timestamp, observed) VALUES (?,?,?,1)",
        ("old", "-100", old),
    )
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, timestamp, observed) VALUES (?,?,?,1)",
        ("new", "-100", new),
    )
    conn.execute("INSERT INTO wakes(kind, chat_id, created_at) VALUES ('message', '-100', ?)", (old,))
    conn.execute("INSERT INTO wakes(kind, chat_id, created_at) VALUES ('message', '-100', ?)", (new,))
    conn.execute("INSERT INTO jev_usage(created_at, route) VALUES (?, 'primary')", (old,))
    conn.execute("INSERT INTO jev_usage(created_at, route) VALUES (?, 'primary')", (new,))
    conn.execute("INSERT INTO digests(surface, content, updated_at) VALUES ('group', 'old', ?)", (old,))
    conn.execute("INSERT INTO digests(surface, content, updated_at) VALUES ('dm', 'new', ?)", (new,))
    conn.commit()
    conn.close()

    result = prune_data.prune_luna_db(
        path,
        days=1,
        batch_size=10,
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    conn = sqlite3.connect(path)
    assert [r[0] for r in conn.execute("SELECT message_id FROM messages").fetchall()] == ["new"]
    assert conn.execute("SELECT COUNT(*) FROM wakes").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM jev_usage").fetchone()[0] == 1
    assert [r[0] for r in conn.execute("SELECT updated_at FROM digests").fetchall()] == [new]
    conn.close()
    assert result == {"messages": 1, "wakes": 1, "jev_usage": 1, "digests": 1,
                      "ambient_judgments": 0, "ambient_intents": 0, "failed": 0}


def test_prune_gateway_db_only_removes_aged_observed_messages(tmp_path):
    path = tmp_path / "state.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "create table messages (id integer primary key, observed integer, timestamp real)"
    )
    old = datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()
    new = datetime(2026, 1, 3, tzinfo=timezone.utc).timestamp()
    conn.executemany(
        "insert into messages values (?, ?, ?)",
        [(1, 1, old), (2, 0, old), (3, 1, new)],
    )
    conn.commit()
    conn.close()

    result = prune_data.prune_gateway_db(
        path,
        days=1,
        batch_size=10,
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    conn = sqlite3.connect(path)
    assert conn.execute("select id from messages order by id").fetchall() == [(2,), (3,)]
    conn.close()
    assert result == {"messages": 1, "failed": 0}


def test_prune_gateway_db_respects_the_indexer_watermark(tmp_path):
    """Rows the indexer has not seen yet are raw log — an outage must not eat them."""
    path = tmp_path / "state.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "create table messages (id integer primary key, observed integer, timestamp real)"
    )
    old = datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()
    conn.executemany(
        "insert into messages values (?, ?, ?)",
        [(1, 1, old), (2, 1, old), (3, 1, old)],
    )
    conn.commit()
    conn.close()

    result = prune_data.prune_gateway_db(
        path,
        days=1,
        batch_size=10,
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
        indexed_through=1,
    )

    conn = sqlite3.connect(path)
    assert conn.execute("select id from messages order by id").fetchall() == [(2,), (3,)]
    conn.close()
    assert result == {"messages": 1, "failed": 0}


def test_prune_all_skips_gateway_prune_without_a_watermark(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from luna_core import db

    index = db.connect(tmp_path / "luna-state.db")
    db.init_db(index)
    index.close()
    gateway = sqlite3.connect(tmp_path / "state.db")
    gateway.execute(
        "create table messages (id integer primary key, observed integer, timestamp real)"
    )
    gateway.execute(
        "insert into messages values (1, 1, ?)",
        (datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp(),),
    )
    gateway.commit()
    gateway.close()

    result = prune_data.prune_all(tmp_path, now=datetime(2026, 1, 2, tzinfo=timezone.utc))

    assert result["gateway"].get("skipped") == "no indexer watermark"
    gateway = sqlite3.connect(tmp_path / "state.db")
    assert gateway.execute("select count(*) from messages").fetchone()[0] == 1
    gateway.close()


def test_prune_all_passes_the_watermark_through(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from luna_core import db

    index = db.connect(tmp_path / "luna-state.db")
    db.init_db(index)
    db.set_meta(index, "observe_row_watermark", "7")
    index.close()
    gateway = sqlite3.connect(tmp_path / "state.db")
    gateway.execute(
        "create table messages (id integer primary key, observed integer, timestamp real)"
    )
    old = datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()
    gateway.executemany("insert into messages values (?, 1, ?)", [(5, old), (9, old)])
    gateway.commit()
    gateway.close()

    result = prune_data.prune_all(tmp_path, now=datetime(2026, 1, 2, tzinfo=timezone.utc))

    assert result["gateway"]["messages"] == 1  # id 5 only; id 9 is past the watermark
    gateway = sqlite3.connect(tmp_path / "state.db")
    assert gateway.execute("select id from messages").fetchall() == [(9,)]
    gateway.close()


def test_honcho_prune_waits_for_conclusion_and_safe_queue_state():
    sql = prune_data.honcho_prune_sql(
        workspace="luna",
        cutoff="2026-01-01T00:00:00+00:00",
        batch_size=100,
    )
    assert "d.deleted_at IS NULL" in sql
    assert "q.processed = false" in sql
    assert "q.error IS NOT NULL" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "DELETE FROM queue" in sql
    assert "DELETE FROM messages" in sql
