"""Component test for luna-memory peer materialization (sync/audit, behind the People page)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "luna" / "plugins" / "luna-memory"
sys.path.insert(0, str(REPO_ROOT / "luna" / "lib"))

from luna_core import db as luna_db  # noqa: E402
from luna_core.identity import IdentityRegistry  # noqa: E402


def _load_plugin():
    spec = importlib.util.spec_from_file_location("luna_memory_plugin", PLUGIN_DIR / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mem_env(tmp_path, monkeypatch):
    index = tmp_path / "luna-state.db"
    honcho = tmp_path / "honcho.json"
    monkeypatch.setenv("LUNA_INDEX_DB", str(index))
    monkeypatch.setenv("LUNA_HONCHO_JSON", str(honcho))
    monkeypatch.setenv("LUNA_CHAT_ID", "-100")
    mod = _load_plugin()

    conn = luna_db.connect(index)
    luna_db.init_db(conn)
    reg = IdentityRegistry(conn)
    reg.set_manual("telegram", "1000000001", peer_id="sam", display_name="Sam",
                   pronouns="he/him", role="owner")
    reg.upsert_auto("telegram", "1002", display_name="Babi")
    conn.close()
    yield mod, honcho, index


def test_sync_peers_writes_alias_map(mem_env):
    mod, honcho, _ = mem_env
    result = mod.sync_peers()
    assert result["aliases_written"] == 2

    data = json.loads(honcho.read_text(encoding="utf-8"))
    aliases = data["hosts"]["hermes"]["userPeerAliases"]
    assert aliases["1000000001"] == "sam"
    assert aliases["1002"] == "telegram_1002"
    assert any(c["peer_id"] == "sam" for c in result["cards"])


def test_audit_peers_reports_ok_when_mapped(mem_env):
    mod, _, index = mem_env
    conn = luna_db.connect(index)
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, user_id, user_name, is_bot, observed) "
        "VALUES ('m1', '-100', '1002', 'Babi', 0, 1)"
    )
    conn.commit()
    conn.close()
    report = mod.audit_peers()
    assert report["ok"] is True
    assert report["unmapped"] == []
