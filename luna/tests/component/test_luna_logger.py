"""Component test for the luna-logger tokenless indexer (no Telegram, no bot token)."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "luna" / "plugins" / "luna-logger"
sys.path.insert(0, str(REPO_ROOT / "luna" / "lib"))

from luna_core import db as luna_db  # noqa: E402

CHAT = "--1000000000000"
OBSERVE_SESSION = "20260625_145905_7936ff9b"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("luna_logger_plugin", PLUGIN_DIR / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _make_state_db(path: Path) -> None:
    conn = sqlite3.connect(path)
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
        "INSERT INTO sessions(id, session_key, chat_id, chat_type) VALUES (?,?,?,?)",
        (OBSERVE_SESSION, f"agent:main:telegram:group:{CHAT}", CHAT, "group"),
    )
    conn.execute(
        "INSERT INTO messages(session_id, role, content, platform_message_id, timestamp, observed) "
        "VALUES (?,?,?,?,?,1)",
        (OBSERVE_SESSION, "user", "[Babi|1002]\nanyone up for pizza?", "501", 1700000000.0),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def logger_env(tmp_path, monkeypatch):
    state = tmp_path / "state.db"
    _make_state_db(state)
    index = tmp_path / "luna-state.db"
    monkeypatch.setenv("LUNA_STATE_DB", str(state))
    monkeypatch.setenv("LUNA_INDEX_DB", str(index))
    yield _load_plugin(), index
    # nothing to tear down


def test_index_once_derives_the_index(logger_env):
    mod, index_path = logger_env
    assert mod.index_once() == 1

    conn = luna_db.connect(index_path, read_only=True)
    row = conn.execute("SELECT * FROM messages WHERE message_id = '501'").fetchone()
    conn.close()
    assert row is not None
    assert row["user_id"] == "1002"
    assert row["content"] == "anyone up for pizza?"
    assert row["peer_id"] == "telegram_1002"


def test_index_once_is_idempotent(logger_env):
    mod, index_path = logger_env
    assert mod.index_once() == 1
    assert mod.index_once() == 0
    conn = luna_db.connect(index_path, read_only=True)
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    conn.close()


def test_index_once_refreshes_the_honcho_alias_map(logger_env, tmp_path, monkeypatch):
    """A member learned by the indexer must reach honcho.json's userPeerAliases without a
    a manual sync from the People page — otherwise upstream generates its own peer id for them and one
    human becomes two Honcho peers."""
    mod, index_path = logger_env
    honcho = tmp_path / "honcho.json"
    monkeypatch.setenv("LUNA_HONCHO_JSON", str(honcho))
    assert mod.index_once() == 1
    data = json.loads(honcho.read_text(encoding="utf-8"))
    aliases = data["hosts"]["hermes"]["userPeerAliases"]
    assert aliases["1002"] == "telegram_1002"


def test_index_files_are_owner_only(logger_env):
    _mod, index_path = logger_env
    conn = luna_db.connect(index_path)
    luna_db.init_db(conn)
    conn.close()
    assert stat.S_IMODE(index_path.stat().st_mode) == 0o600
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{index_path}{suffix}")
        if sidecar.exists():
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600


def test_index_once_without_state_db_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_STATE_DB", str(tmp_path / "missing.db"))
    monkeypatch.setenv("LUNA_INDEX_DB", str(tmp_path / "luna-state.db"))
    mod = _load_plugin()
    assert mod.index_once() == 0  # never raises


def test_no_bot_token_anywhere(logger_env):
    """The indexer must not reference a Telegram token."""
    src = (PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN" not in src
    assert "getUpdates" not in src


def test_honcho_sync_is_guarded_when_sdk_unavailable(logger_env):
    mod, index_path = logger_env
    mod.index_once()
    conn = luna_db.connect(index_path)
    try:
        # The honcho SDK isn't installed in the test venv -> guarded, returns 0, never raises.
        assert mod.sync_honcho_room(conn) == 0
    finally:
        conn.close()


def test_honcho_sync_respects_disable_flag(logger_env, monkeypatch):
    mod, index_path = logger_env
    monkeypatch.setenv("LUNA_LOGGER_SYNC_HONCHO", "false")
    conn = luna_db.connect(index_path)
    try:
        assert mod.sync_honcho_room(conn) == 0
    finally:
        conn.close()
