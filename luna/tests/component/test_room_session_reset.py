"""Local room administration must reset the exact shared route without losing history."""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.session import AsyncSessionStore, SessionSource, SessionStore
from gateway.slash_commands_session import GatewaySessionCommandsMixin
from luna_core.room_sessions import reset_room_session


@pytest.fixture
def room(tmp_path, monkeypatch):
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(root))
    store = SessionStore(root / "sessions", GatewayConfig(group_sessions_per_user=True))
    shared = SessionSource(platform=Platform.TELEGRAM, chat_id="-100123", chat_type="group")
    personal = SessionSource(platform=Platform.TELEGRAM, chat_id="-100123", chat_type="group", user_id="123")
    entry = store.get_or_create_session(shared)
    person = store.get_or_create_session(personal)
    store._db.append_message(entry.session_id, "user", "old room history")
    runner = SimpleNamespace(
        session_store=store, async_session_store=AsyncSessionStore(store),
        _running=True, _draining=False,
        _session_key_for_source=store._generate_session_key,
        _profile_scope_for_source=lambda source: nullcontext(),
        _is_session_running=lambda key: False,
        _delivery_adapter_for=lambda source: None,
        _invalidate_session_run_generation=Mock(), _release_running_agent_state=Mock(),
        _cleanup_old_agent_for_reset=AsyncMock(), _evict_cached_agent=Mock(),
        _clear_conversation_scope=Mock(), _fire_session_reset_hooks=AsyncMock(),
        _reset_notice_session_info=lambda source: "", _telegram_topic_new_header=lambda source: "",
        _is_telegram_topic_lane=lambda source: False, _session_db=None,
    )
    runner._handle_reset_command = lambda event: GatewaySessionCommandsMixin._handle_reset_command(runner, event)
    return runner, entry, person


@pytest.mark.asyncio
async def test_exact_shared_reset_preserves_history_and_personal_session(room):
    runner, old, person = room
    result = await reset_room_session(runner, {"session_key": old.session_key, "expected_session_id": old.session_id})
    assert result["reset"] is True
    assert result["old_session_id"] == old.session_id
    fresh = runner.session_store.lookup_by_session_key(old.session_key)
    assert fresh.session_id == result["new_session_id"] != old.session_id
    assert runner.session_store.lookup_by_session_key(person.session_key).session_id == person.session_id
    db = runner.session_store._db
    assert db.get_session(old.session_id)["end_reason"] == "session_reset"
    assert db.get_session(fresh.session_id)["parent_session_id"] == old.session_id
    assert db.get_messages(old.session_id)[0]["content"] == "old room history"
    assert db.get_messages(fresh.session_id) == []
    runner._evict_cached_agent.assert_called_once_with(old.session_key)
    runner._clear_conversation_scope.assert_called_once_with(old.session_key, reason="session_reset")
    runner._fire_session_reset_hooks.assert_awaited_once()
    assert not runner._room_reset_keys


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["personal", "changed", "missing"])
async def test_refuses_wrong_route_or_stale_id_without_reset(room, target):
    runner, old, person = room
    params = {"session_key": old.session_key, "expected_session_id": old.session_id}
    if target == "personal":
        params = {"session_key": person.session_key, "expected_session_id": person.session_id}
    elif target == "changed":
        params["expected_session_id"] = "stale-id"
    else:
        params["session_key"] = "agent:main:telegram:group:missing"
    result = await reset_room_session(runner, params)
    assert result["reset"] is False
    assert runner.session_store.lookup_by_session_key(old.session_key).session_id == old.session_id
    runner._evict_cached_agent.assert_not_called()


@pytest.mark.asyncio
async def test_refuses_busy_room_instead_of_interrupting(room):
    runner, old, _ = room
    runner._is_session_running = lambda key: True
    result = await reset_room_session(runner, {"session_key": old.session_key, "expected_session_id": old.session_id})
    assert result["reset"] is False
    assert result["reason"] == "busy"
    runner._cleanup_old_agent_for_reset.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_barrier_is_held_during_cleanup_and_released_on_error(room):
    runner, old, _ = room
    entered, finish = asyncio.Event(), asyncio.Event()
    async def cleanup(key):
        entered.set()
        await finish.wait()
        raise RuntimeError("fixture cleanup failure")
    runner._cleanup_old_agent_for_reset = cleanup
    task = asyncio.create_task(reset_room_session(runner, {"session_key": old.session_key, "expected_session_id": old.session_id}))
    await entered.wait()
    assert old.session_key in runner._room_reset_keys
    duplicate = await reset_room_session(runner, {"session_key": old.session_key, "expected_session_id": old.session_id})
    assert duplicate["reset"] is False
    finish.set()
    with pytest.raises(RuntimeError, match="fixture cleanup failure"):
        await task
    assert old.session_key not in runner._room_reset_keys


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before_admission", "during_admission"])
async def test_ingress_cannot_claim_a_room_during_reset(room, when):
    from gateway.run import GatewayRunner
    from gateway.platforms.event import MessageEvent
    runner, entry, _ = room
    runner._room_reset_keys = {entry.session_key} if when == "before_admission" else set()
    runner._hm_admit_event = AsyncMock(return_value=(MessageEvent(text="wake", source=entry.origin, internal=True), entry.origin, True))
    runner._hm_estop_gate = lambda *args: None
    async def intercept(*args):
        runner._room_reset_keys.add(entry.session_key)
    runner._hm_pending_reply_intercepts = intercept
    runner._hm_evict_idle_stale_agent = lambda key: None
    runner._hm_dispatch_idle_commands = AsyncMock(return_value=(False, None))
    runner._claim_active_session_slot = Mock(side_effect=AssertionError("resetting room must not claim a turn"))
    result = await GatewayRunner._handle_message(runner, MessageEvent(text="wake", source=entry.origin, internal=True))
    assert result is None
    runner._claim_active_session_slot.assert_not_called()


@pytest.mark.asyncio
async def test_ambient_injection_is_refused_during_room_reset(room):
    from gateway.run import GatewayRunner
    runner, entry, _ = room
    runner._room_reset_keys = {entry.session_key}
    runner.async_session_store = SimpleNamespace(lookup_by_session_key=AsyncMock())
    assert await GatewayRunner._dispatch_plugin_message_injection(
        runner, session_key=entry.session_key, content="wake", plugin_id="fixture",
    ) is False
    runner.async_session_store.lookup_by_session_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_control_socket_and_operator_cli_reset_exact_room(room, tmp_path):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    from gateway.control_socket import GatewayControlServer
    from luna_core.room_sessions import room_control_verbs
    runner, old, person = room
    socket_home = tmp_path / "socket"
    socket_home.mkdir()
    server = GatewayControlServer(socket_home, verb_handlers=room_control_verbs(runner))
    assert await server.start()
    env = dict(os.environ)
    source = Path(__file__).resolve().parents[3]
    env["PYTHONPATH"] = os.pathsep.join((str(source / "luna/lib"), str(source)))
    def cli(*args):
        return subprocess.run([sys.executable, "-m", "luna_cli.room_sessions", "--home", str(socket_home), *args],
                              env=env, capture_output=True, text=True, timeout=15)
    try:
        listing = await asyncio.to_thread(cli, "list")
        assert listing.returncode == 0, listing.stderr
        rooms = json.loads(listing.stdout)["rooms"]
        assert [item["session_key"] for item in rooms] == [old.session_key]
        result = await asyncio.to_thread(cli, "reset", old.session_key, "--expected-session-id", old.session_id)
        assert result.returncode == 0, result.stderr
        outcome = json.loads(result.stdout)
        assert outcome["reset"] is True
        assert outcome["new_session_id"] != old.session_id
        duplicate = await asyncio.to_thread(cli, "reset", old.session_key, "--expected-session-id", old.session_id)
        assert duplicate.returncode != 0
        assert json.loads(duplicate.stdout)["reason"] == "session_changed"
        assert runner.session_store.lookup_by_session_key(person.session_key).session_id == person.session_id
    finally:
        await server.stop()
