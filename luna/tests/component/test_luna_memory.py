"""Component tests for the luna-memory provider: identity learning + bounded recall."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "luna" / "plugins" / "luna-memory"
sys.path.insert(0, str(REPO_ROOT / "luna" / "lib"))


def _load_plugin():
    spec = importlib.util.spec_from_file_location("luna_memory_plugin", PLUGIN_DIR / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _FakeBackend:
    """Stands in for the bundled Honcho provider (not importable in tests)."""

    def __init__(self, recall: str):
        self._recall = recall

    def prefetch(self, query, *, session_id=""):
        return self._recall


@pytest.fixture()
def provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("luna:\n  setup:\n    memory: enabled\n")
    monkeypatch.setenv("LUNA_INDEX_DB", str(tmp_path / "luna-state.db"))
    monkeypatch.setenv("LUNA_CHAT_ID", "-1000000000000")
    monkeypatch.setenv("LUNA_MEMORY_RECALL_MAX_CHARS", "300")
    mod = _load_plugin()
    p = mod.LunaMemoryProvider()
    p.initialize("s1", platform="telegram", user_id="1000000001", user_name="Sam")
    yield mod, p
    p.shutdown()


def test_provider_name_and_availability(provider):
    _, p = provider
    assert p.name == "luna-memory"
    assert p.is_available() is True


def test_initialize_learns_identity(provider):
    mod, p = provider
    from luna_core.identity import IdentityRegistry

    reg = IdentityRegistry(p._ensure_conn())
    assert reg.resolve("telegram", "1000000001") == "telegram_1000000001"


def test_prefetch_is_bounded(provider, monkeypatch):
    mod, p = provider
    # A runaway recall backend must still respect the ceiling (the 58,335-char regression).
    p._backend = _FakeBackend("\n\n".join(f"section {i} " + "x" * 400 for i in range(50)))
    out = p.prefetch("anything")
    assert len(out) <= 300
    status = p.recall_status()
    assert status["truncated"] is True
    assert status["dropped"] >= 1


def test_prefetch_excludes_room_context(provider):
    """Room context is owned by luna-room: a second rendition (and the DM/CLI leak) must not exist."""
    mod, p = provider
    conn = p._ensure_conn()
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, user_id, user_name, content, timestamp, "
        "is_bot, observed) VALUES (?,?,?,?,?,?,0,1)",
        ("r1", "-1000000000000", "u1", "Alex", "secret group chatter", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    out = p.prefetch("anything")
    assert "[Room context" not in out
    assert "secret group chatter" not in out


def test_group_recall_is_topic_scoped_and_excludes_other_pending_requests(provider, tmp_path):
    from luna_core.room import record_inbound
    from luna_core.room_dispatch import CURRENT_TARGET, Target
    _, p = provider
    p.initialize("group-session", platform="telegram", user_id="1000000001", chat_id="group", chat_type="forum", thread_id="55")
    assert p._backend is None
    conn = p._ensure_conn()
    for mid, topic, body in [("1", "55", "SAME_TOPIC_HISTORY"), ("2", "55", "OTHER_PENDING_QUESTION"), ("3", "66", "OTHER_TOPIC_HISTORY")]:
        record_inbound(conn, message_id=mid, chat_id="group", thread_id=topic, user_id="1000000001", content=body)
    token = CURRENT_TARGET.set(Target(str(tmp_path), "telegram", "group", "55", "1000000001", "1", ("1",), frozenset({"2"}), 999))
    try:
        recall = p.prefetch("history")
    finally:
        CURRENT_TARGET.reset(token)
    assert "SAME_TOPIC_HISTORY" in recall
    assert "OTHER_PENDING_QUESTION" not in recall and "OTHER_TOPIC_HISTORY" not in recall


def test_prefetch_ranks_relevant_sections_first(provider):
    mod, p = provider
    filler = "unrelated small talk about the weather " * 5
    relevant = "the deploy plan for friday needs review"
    p._backend = _FakeBackend(f"{filler}\n\n{relevant}\n\n{filler}")
    out = p.prefetch("who is reviewing the deploy plan?")
    assert "deploy plan" in out


def test_recall_status_reports_the_last_budget(provider):
    mod, p = provider
    assert p.recall_status()["truncated"] is False
    p._backend = _FakeBackend("some recall")
    p.prefetch("query")
    status = p.recall_status()
    assert status["chars"] > 0 and status["backend"] == "honcho"


def test_sync_turn_attributes_author(provider):
    mod, p = provider
    p.sync_turn("hi", "hello", session_id="s1", turn_author={"id": "555", "name": "Babi"})
    from luna_core.identity import IdentityRegistry

    reg = IdentityRegistry(p._ensure_conn())
    assert reg.resolve("telegram", "555") == "telegram_555"


def test_identity_signature(provider):
    _, p = provider
    sig = p.identity_signature()
    assert sig["provider"] == "luna-memory"


def test_sync_turn_writes_identity_only_never_injected_context(provider):
    """The write path must not persist prefetch/sidecar context — only the author mapping."""
    mod, p = provider
    p._backend = _FakeBackend("[Room context — recent messages]\nAlex: leaked")
    injected = p.prefetch("hi")
    assert injected  # recall is injected into the turn...
    p.sync_turn(injected, "my reply", session_id="s1",
                turn_author={"id": "555", "name": "Babi"})
    conn = p._ensure_conn()
    # ...but never written back as a message row or identity content.
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    from luna_core.identity import IdentityRegistry
    reg = IdentityRegistry(conn)
    assert reg.resolve("telegram", "555") == "telegram_555"
    assert reg.get("telegram", "555").display_name == "Babi"
