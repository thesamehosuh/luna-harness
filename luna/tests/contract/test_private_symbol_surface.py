"""Contract tests: the private upstream symbols the harness depends on must exist.

These are *source-level* checks (no imports, no runtime), so they run in any environment and fail
loudly the moment an upstream merge renames or removes a symbol we rely on. A failure here BLOCKS
the merge until the pin/patch is reconciled (see AGENTS.md §6/§7).
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.is_file(), f"missing upstream file: {rel}"
    return path.read_text(encoding="utf-8", errors="replace")


def test_sidecar_note_method_exists():
    """Cache-safe per-turn injection (luna-room's primary path)."""
    cache = _read("gateway/run_agent_cache.py")
    assert "_set_pending_turn_sidecar_notes" in cache, (
        "gateway/run_agent_cache.py no longer defines _set_pending_turn_sidecar_notes — "
        "luna-room's cache-safe injection path is broken. Do NOT fall back to channel_prompt: "
        "it is system-level and inside the cached-agent signature (AGENTS.md §3 invariant 1), so "
        "the correct response is to fail closed and drop the room block for that turn."
    )
    assert "_set_pending_turn_sidecar_notes" in _read("gateway/run_turn.py"), (
        "the sidecar notes are no longer consumed in gateway/run_turn.py"
    )


def test_agent_config_signature_exists():
    """The prompt-cache invariant we must not perturb."""
    joined = _read("gateway/run_agent_cache.py") + _read("gateway/run_turn.py")
    assert "_agent_config_signature" in joined or "agent_config_signature" in joined


def test_observe_capture_symbols_exist():
    """Single-token room log: observe_unmentioned_group_messages + the shared observe source."""
    adapter = _read("plugins/platforms/telegram/adapter.py")
    assert "observe_unmentioned_group_messages" in adapter, (
        "telegram adapter no longer exposes observe_unmentioned_group_messages — the single-token "
        "room log depends on it."
    )
    assert "_telegram_group_observe_shared_source" in adapter, (
        "the shared observe session helper was renamed; luna-logger's isolation assumption is at risk."
    )


def test_attribution_symbols_exist():
    """Deterministic per-message author attribution."""
    peers = _read("plugins/memory/honcho/session_peers.py")
    assert "resolve_author_peer_id" in peers
    session = _read("plugins/memory/honcho/session.py")
    assert "author_peer_id" in session, (
        "per-message author attribution key gone; per-identity memory would regress."
    )


def test_inbound_tap_symbols_exist():
    """pre_gateway_dispatch — the inbound tap luna-room uses."""
    assert "pre_gateway_dispatch" in _read("hermes_cli/plugins.py")
    assert "_hm_pre_gateway_dispatch_hook" in _read("gateway/run_inbound.py")


def test_memory_provider_abc_exists():
    assert "class MemoryProvider" in _read("agent/memory_provider.py")


def test_memory_provider_discovery_marker():
    """A user plugin dir is treated as a memory provider when its __init__ mentions the contract."""
    src = _read("plugins/memory/__init__.py")
    assert "_is_memory_provider_dir" in src
    assert "MemoryProvider" in src


def test_turn_author_threading_exists():
    src = _read("gateway/run_turn_runner.py")
    assert "turn_author" in src, "turn_author is no longer threaded from the transport"


def test_native_context_projection_seams_exist():
    for path, symbol in (
        ("agent/turn_context.py", "substitute_api_content"),
        ("agent/replay_cleanup.py", "canonicalize_replay_history"),
        ("agent/session_persistence.py", "_durable_content"),
    ):
        assert f"def {symbol}(" in _read(path), f"Native context projection lost {symbol}"
