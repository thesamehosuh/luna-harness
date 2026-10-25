"""Data retention enforcement — the in-process half of ``luna.data.retention_days``.

The pruning *logic* lives in ``luna/tools/prune_data.py``, and ``install.sh`` has always installed
a daily systemd timer (``luna-data-retention.timer``) that runs that CLI. So retention was **not**
simply absent — it was enforced only on that one path, which means:

- deployments that never ran ``install.sh``'s systemd setup (manual gateway start, containers
  without systemd, a second gateway process) had **no enforcement at all**, and the observe
  transcript — every unmentioned group message, full text — grew without bound;
- enforcement was once a day, so a burst of room chatter could sit unpruned for up to 24h.

This module adds in-process enforcement from the indexer loop, which runs wherever the gateway
runs. It lives in ``luna_core`` because that is the only Luna package on the gateway's
``sys.path`` (``luna/tools`` is an operator-only tree). Both paths are safe to run together: the
deletes are idempotent, and each takes the write lock briefly.

The same pass also prunes owned native stores and ended engine sessions, expires backups, and
executes managed Honcho maintenance inside its private Docker services.
"""

from __future__ import annotations

from luna_core.runtime import home as runtime_home, getenv

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_RETENTION_DAYS = 1
DEFAULT_BATCH_SIZE = 1000

# Tables pruned from ``luna-state.db``, each with its own age column.
_LUNA_DB_TARGETS = (
    ("messages", "timestamp"),
    ("wakes", "created_at"),
    ("jev_usage", "created_at"),
    ("ambient_judgments", "created_at"),
    ("ambient_intents", "created_at"),
    ("digests", "updated_at"),
)


def _home(explicit: str | None = None) -> Path:
    return Path(explicit or str(runtime_home())).expanduser()


def _db_path(env_name: str, home: Path, filename: str) -> Path:
    """Resolve a Luna database exactly the way its writer does.

    Every other Luna surface honours the documented ``LUNA_STATE_DB`` / ``LUNA_INDEX_DB``
    overrides (luna-logger, luna-room, luna-ambient, luna-memory, luna_cli.tune). Hardcoding
    ``home / filename`` here meant that on any deployment using those overrides, retention pruned
    a database nothing reads while the real transcript grew forever — a silent no-op for the very
    bug this module exists to close.
    """
    raw = str(getenv(env_name) or "").strip()
    return Path(os.path.expandvars(raw)).expanduser() if raw else home / filename


def _config(home: Path) -> dict[str, Any] | None:
    """Config for *home*.

    The canonical adapter reads the ambient ``HERMES_HOME`` (and the engine's cached config), which
    is right in production — the indexer loop always runs against the live home. When a caller
    passes an explicit different home, read that file directly so config and the databases being
    pruned can never come from two different homes.

    Returns ``None`` when the config could not be read at all. The caller must then skip: falling
    back to ``{}`` would resolve the shipped 1-day default, so one transient read error or a
    hand-edit typo would quietly delete a month of history.
    """
    try:
        ambient = _home()
        if home.resolve() != ambient.resolve():
            import yaml

            return yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    try:
        from luna_core import config_read

        return config_read.load_config()
    except Exception:
        return None


def _value(data: dict[str, Any], key: str, default: Any) -> Any:
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _int_value(data: dict[str, Any], key: str, default: int, env_name: str) -> int:
    raw = getenv(env_name)
    try:
        return int(raw) if raw is not None and raw.strip() else int(_value(data, key, default))
    except (TypeError, ValueError):
        return default


def _bool_value(data: dict[str, Any], key: str, default: bool, env_name: str) -> bool:
    raw = getenv(env_name)
    if raw is None or not raw.strip():
        return bool(_value(data, key, default))
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def cutoff_iso(days: int, now: datetime | None = None) -> str:
    """ISO-8601 age cutoff string shared by the SQLite and Honcho pruners."""
    current = now or datetime.now(timezone.utc)
    return (current - timedelta(days=days)).isoformat()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def prune_luna_db(
    path: Path, *, days: int, batch_size: int, now: datetime | None = None
) -> dict[str, int]:
    result = {"messages": 0, "wakes": 0, "jev_usage": 0, "digests": 0, "failed": 0}
    if days <= 0 or not path.exists():
        return result
    cutoff = cutoff_iso(days, now)
    # Delete by ``rowid``: the PK shapes differ per table (``messages.message_id`` is TEXT,
    # ``digests.surface`` is TEXT, the ledgers use INTEGER ids) and hardcoding a column name is
    # how the pruner silently failed against the real schema. Every table here is a rowid table.
    try:
        conn = sqlite3.connect(path, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN IMMEDIATE")
        for table, column in _LUNA_DB_TARGETS:
            if not _table_exists(conn, table):
                continue
            while True:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE rowid IN "
                    f"(SELECT rowid FROM {table} WHERE {column} < ? LIMIT ?)",
                    (cutoff, batch_size),
                )
                result[table] = result.get(table, 0) + max(0, cursor.rowcount)
                if cursor.rowcount < batch_size:
                    break
        if _table_exists(conn, "memory_outbox"):
            conn.execute("DELETE FROM memory_outbox WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.chat_id=memory_outbox.chat_id AND m.message_id=memory_outbox.message_id)")
        conn.commit()
        conn.close()
    except (OSError, sqlite3.Error):
        try:
            conn.rollback()
            conn.close()
        except (UnboundLocalError, sqlite3.Error):
            pass
        # Every delete is in one transaction, so a failure here rolls all of them back. Zero the
        # counts: reporting rows as pruned when they are still on disk is how a silently broken
        # pruner stays invisible.
        result = {key: 0 for key in result}
        result["failed"] = 1
    return result


def prune_gateway_db(
    path: Path,
    *,
    days: int,
    batch_size: int,
    now: datetime | None = None,
    indexed_through: int | None = None,
) -> dict[str, int | float]:
    """Prune observed rows from the gateway's ``state.db``.

    ``indexed_through`` is the indexer watermark (the ``messages.id`` of the last indexed observe
    row). Rows above it are raw log the derived index has never seen — deleting them first is how
    an indexer outage longer than the retention window permanently loses room history. Pass the
    watermark and those rows survive until the indexer catches up.
    """
    result: dict[str, int | float] = {"messages": 0, "failed": 0}
    if days <= 0 or not path.exists():
        return result
    current = now or datetime.now(timezone.utc)
    cutoff = (current - timedelta(days=days)).timestamp()
    bound = "AND id <= ?" if indexed_through is not None else ""
    params: tuple[Any, ...] = (
        (cutoff, int(indexed_through), batch_size)
        if indexed_through is not None
        else (cutoff, batch_size)
    )
    try:
        conn = sqlite3.connect(path, timeout=2)
        conn.execute("PRAGMA busy_timeout=2000")
        conn.execute("BEGIN IMMEDIATE")
        while True:
            cursor = conn.execute(
                f"DELETE FROM messages WHERE id IN "
                f"(SELECT id FROM messages WHERE observed = 1 AND timestamp < ? {bound} "
                f"ORDER BY id LIMIT ?)",
                params,
            )
            result["messages"] += max(0, cursor.rowcount)
            if cursor.rowcount < batch_size:
                break
        conn.commit()
        conn.close()
    except (OSError, sqlite3.Error):
        try:
            conn.rollback()
            conn.close()
        except (UnboundLocalError, sqlite3.Error):
            pass
        result = {"messages": 0, "failed": 1}
    return result


def observe_watermark(path: Path) -> int | None:
    """The indexer's observe-row watermark from ``luna-state.db``'s meta table."""
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(path, timeout=2)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'observe_row_watermark'"
        ).fetchone()
        conn.close()
        return int(row[0]) if row and row[0] else None
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return None


def enforce(home: str | Path | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    """Apply the configured retention window to the SQLite stores. Never raises.

    Returns a summary dict; ``skipped`` explains a no-op so the caller can log it at debug level
    without treating it as a failure.
    """
    root = _home(str(home) if home is not None else None)
    data = _config(root)
    if data is None:
        # Unreadable config: skip rather than fall back to the 1-day default. Deleting on a
        # transient read failure is unrecoverable; waiting for the next pass is not.
        return {"skipped": "config unreadable"}
    if not _bool_value(data, "luna.data.auto_prune", True, "LUNA_DATA_AUTO_PRUNE"):
        return {"skipped": "auto_prune disabled"}
    days = _int_value(
        data, "luna.data.retention_days", DEFAULT_RETENTION_DAYS, "LUNA_DATA_RETENTION_DAYS"
    )
    if days <= 0:
        return {"skipped": "retention_days <= 0"}
    batch_size = max(
        1,
        _int_value(data, "luna.data.batch_size", DEFAULT_BATCH_SIZE, "LUNA_DATA_BATCH_SIZE"),
    )
    summary: dict[str, Any] = {"retention_days": days, "luna": {}, "gateway": {}}
    try:
        index_db = _db_path("LUNA_INDEX_DB", root, "luna-state.db")
        state_db = _db_path("LUNA_STATE_DB", root, "state.db")
        summary["luna"] = prune_luna_db(
            index_db, days=days, batch_size=batch_size, now=now
        )
        if _bool_value(data, "luna.data.prune_gateway_state", True, "LUNA_PRUNE_GATEWAY_STATE"):
            watermark = observe_watermark(index_db)
            if watermark is None:
                # No indexer watermark: every observed row may still be un-indexed raw log.
                summary["gateway"] = {"messages": 0, "failed": 0, "skipped": "no indexer watermark"}
            else:
                summary["gateway"] = prune_gateway_db(
                    state_db,
                    days=days,
                    batch_size=batch_size,
                    now=now,
                    indexed_through=watermark,
                )
    except Exception:
        return {"skipped": "retention pass failed"}
    summary["native"] = prune_native(root, days=days, now=now)
    if (root / "honcho/docker-compose.yml").exists():
        try:
            import importlib.util
            path = Path(__file__).resolve().parents[2] / "tools/prune_data.py"
            spec = importlib.util.spec_from_file_location("luna_managed_pruner", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            summary["honcho"] = module.prune_honcho(data=data, days=days, batch_size=batch_size, now=now, home=root)
        except Exception:
            summary["honcho"] = {"failed": 1}
    backup_days = _int_value(data, "luna.data.backup_days", 7, "LUNA_BACKUP_DAYS")
    if backup_days > 0:
        cutoff = (now or datetime.now(timezone.utc)).timestamp() - backup_days * 86400
        for archive in (root / "backups/luna").glob("*.tar.gz"):
            if not archive.is_symlink() and archive.stat().st_mtime < cutoff:
                archive.unlink()
    # Canonical ended sessions use the same policy, preserving active write leases.
    if state_db.exists():
        try:
            from hermes_state import SessionDB
            session_db = SessionDB(state_db)
            try:
                summary["sessions"] = session_db.prune_sessions(older_than_days=days, sessions_dir=root / "sessions", exclude_active_write_guards=True)
            finally:
                session_db.close()
        except Exception:
            summary["sessions"] = {"failed": 1}
    import json
    summary["checked_at"] = (now or datetime.now(timezone.utc)).isoformat()
    summary["last_success_at"] = summary["checked_at"] if not any(isinstance(item, dict) and item.get("failed") for item in summary.values()) else None
    temporary = root / ".retention-status.tmp"
    temporary.write_text(json.dumps(summary))
    temporary.chmod(0o600)
    os.replace(temporary, root / ".retention-status.json")
    return summary


def auto_prune_interval_seconds(default_minutes: int = 60) -> int:
    """Configured pass cadence. Env wins, then config, then the supplied default."""
    env = getenv("LUNA_DATA_AUTO_PRUNE_INTERVAL_MINUTES")
    if env is not None and env.strip():
        try:
            return max(1, int(env)) * 60
        except (TypeError, ValueError):
            pass
    data = _config(_home()) or {}
    minutes = _int_value(
        data,
        "luna.data.auto_prune_interval_minutes",
        default_minutes,
        "LUNA_DATA_AUTO_PRUNE_INTERVAL_MINUTES",
    )
    return max(1, minutes) * 60


def prune_native(root, *, days, now=None):
    """Native stores are owned session directories; no dependence on a private native DB schema."""
    import shutil
    from luna_core.native_resources import idle
    cutoff = (now or datetime.now(timezone.utc)).timestamp() - days * 86400
    result = {"sessions": 0, "attachments": 0, "legacy_stores": 0, "active_skipped": 0, "failed": 0}
    native = root / "opencode"
    for directory in (native / "sessions").glob("*"):
        if not directory.is_dir() or directory.is_symlink():
            continue
        stamp = directory / ".created"
        if (stamp.stat().st_mtime if stamp.exists() else directory.stat().st_mtime) >= cutoff:
            continue
        handle = idle(native, directory.name)
        if handle is None:
            result["active_skipped"] += 1
            continue
        try:
            shutil.rmtree(directory)
            result["sessions"] += 1
        except OSError:
            result["failed"] += 1
        finally:
            handle.close()
    for path in (native / "attachments").glob("*"):
        if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
            try:
                path.unlink()
                result["attachments"] += 1
            except OSError:
                result["failed"] += 1
    # Earlier versions shared these owned raw stores across native sessions. Defer while
    # any process still names them; after upgrade they expire as a whole, by last write.
    legacy = [p for name in ("data", "home", "cache", "state") if (p := native / name).is_dir() and not p.is_symlink()]
    if legacy:
        try:
            import psutil
            active = False
            prefixes = tuple(str(p.resolve()) for p in legacy)
            attributes = ["pid", "cmdline"] + (["uids"] if hasattr(os, "getuid") else [])
            for process in psutil.process_iter(attributes):
                if process.info.get("uids") and process.info["uids"].real != os.getuid():
                    continue
                try:
                    values = [*(process.info["cmdline"] or []), *process.environ().values()]
                    if any(value.startswith(prefixes) for value in values):
                        active = True
                        break
                except psutil.NoSuchProcess:
                    continue
            if active:
                result["active_skipped"] += len(legacy)
            else:
                for directory in legacy:
                    newest = max([directory.stat().st_mtime, *[p.stat().st_mtime for p in directory.rglob("*") if not p.is_symlink()]])
                    if newest < cutoff:
                        shutil.rmtree(directory)
                        result["legacy_stores"] += 1
        except (OSError, psutil.Error):
            result["failed"] += 1
    return result


def status(home=None):
    import json
    path = _home(str(home) if home else None) / ".retention-status.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {"last_success_at": None, "coverage": "not yet checked"}
