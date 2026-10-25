"""Deterministic group-burst scheduling, transport targeting and cache-safe context."""
import asyncio
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest

from gateway.config import Platform
from gateway.platforms.event import MessageEvent, MessageType
from gateway.session import SessionSource, build_session_key
from luna_core.room_dispatch import Coordinator, Policy, Target, CURRENT_TARGET, can_deliver, current_target, reply_anchor, validate_policy, _store


def event(index, *, user=None, chat="room-a", thread=None, text=None, parent=None):
    return MessageEvent(source=SessionSource(platform=Platform.TELEGRAM, chat_id=chat, chat_type="group", user_id=user or f"u_{index}", thread_id=thread),
        message_id=str(100 + index), text=text or f"question {index}?", message_type=MessageType.TEXT,
        raw_message=SimpleNamespace(reply_to_message=SimpleNamespace(message_id=parent) if parent else None))


class Adapter:
    def __init__(self, root):
        self.root = root
        self._background_tasks = set()
        self._session_tasks = {}
        self._bot = SimpleNamespace(id=42)
        self.running = self.peak = 0
        self.room_active, self.room_peak = {}, {}
        self.started, self.sent, self.notes = [], [], []
        self.hold = None

    def _event_session_key(self, value):
        return build_session_key(value.source)

    def _media_delivery_scope(self, source):
        return nullcontext()

    def _start_session_processing(self, value, key):
        task = asyncio.create_task(self._process(value, key))
        self._session_tasks[key] = task
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return True

    async def _process(self, value, key):
        room = value.source.chat_id, value.source.thread_id
        self.running += 1
        self.peak = max(self.peak, self.running)
        self.room_active[room] = self.room_active.get(room, 0) + 1
        self.room_peak[room] = max(self.room_peak.get(room, 0), self.room_active[room])
        try:
            self.started.append(value)
            target = current_target()
            self.notes.append(target.note())
            assert target.matches(value.source)
            if self.hold:
                await self.hold.wait()
            await asyncio.sleep(0)
            if can_deliver(value):
                self.sent.append((value.source.chat_id, value.source.thread_id, value.source.user_id, reply_anchor(value), value.text))
        finally:
            self.running -= 1
            self.room_active[room] -= 1
            self._session_tasks.pop(key, None)

    async def cancel_session_processing(self, key, **kwargs):
        task = self._session_tasks.get(key)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def send(self, **kwargs):
        self.sent.append((kwargs["chat_id"], (kwargs.get("metadata") or {}).get("thread_id"), None, None, kwargs["content"]))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    adapter = Adapter(tmp_path)
    decisions = []
    cfg = replace(Policy(), settle_seconds=0, response_gap_seconds=0)
    coordinator = Coordinator(adapter, tmp_path, cfg, record=lambda root, item, state, reason: decisions.append((item.message_ids, state, reason)))
    return coordinator, adapter, decisions


async def idle(coordinator):
    await asyncio.gather(*(lane.task for lane in coordinator.lanes.values() if lane.task))


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)
    await asyncio.wait_for(wait(), 5)


@pytest.mark.asyncio
async def test_ten_people_get_one_active_voice_and_bounded_selected_replies(setup):
    coordinator, adapter, decisions = setup
    for index in range(10):
        await coordinator.submit(event(index))
    await idle(coordinator)
    answers = [row for row in adapter.sent if row[2] is not None]
    notices = [row for row in adapter.sent if row[2] is None]
    assert adapter.peak == 1
    assert len(answers) == 3 and len(notices) == 1
    assert len({row[3] for row in answers}) == 3
    assert len([row for row in decisions if row[2] == "burst_limit"]) == 7
    assert all(len(value._luna_reply_target.excluded_message_ids) >= 7 for value in adapter.started)
    assert current_target() is None


@pytest.mark.asyncio
async def test_distinct_rooms_and_topics_continue_within_global_bound(setup):
    coordinator, adapter, decisions = setup
    coordinator.policy = replace(coordinator.policy, max_parallel_rooms=2)
    adapter.hold = asyncio.Event()
    for index in range(6):
        await coordinator.submit(event(index, chat="same-group", thread=f"topic-{index}"))
    for _ in range(100):
        if len(adapter.started) == 2:
            break
        await asyncio.sleep(0)
    assert len(adapter.started) == 2
    adapter.hold.set()
    await idle(coordinator)
    assert adapter.peak == 2
    assert all(count == 1 for count in adapter.room_peak.values())
    assert len(adapter.sent) == 6


@pytest.mark.asyncio
async def test_only_same_author_and_reply_chain_fragments_can_combine(setup):
    coordinator, adapter, decisions = setup
    coordinator.policy = replace(coordinator.policy, settle_seconds=1, max_turns_per_burst=10, max_turns_per_minute=10)
    coordinator.clock = lambda: 100
    async def settle(_seconds):
        await asyncio.sleep(0)
    coordinator.sleep = settle
    await coordinator.submit(event(1, user="same", text="first fragment", parent="50"))
    await coordinator.submit(event(2, user="same", text="second fragment", parent="50"))
    await coordinator.submit(event(3, user="other", text="someone else's question", parent="50"))
    await coordinator.submit(event(4, user="same", text="different reply chain", parent="51"))
    await idle(coordinator)
    assert len(adapter.started) == 3
    merged = next(value for value in adapter.started if "first fragment" in value.text)
    assert merged.source.user_id == "same" and merged.message_id == "102"
    assert "second fragment" in merged.text and "someone else" not in merged.text


@pytest.mark.asyncio
async def test_duplicate_delivery_does_not_start_another_model_turn(setup):
    coordinator, adapter, decisions = setup
    await coordinator.submit(event(1))
    await coordinator.submit(event(1))
    await idle(coordinator)
    await coordinator.submit(event(1))
    await idle(coordinator)
    assert len(adapter.started) == 1


def test_recipient_profile_and_deadline_are_code_enforced(setup):
    coordinator, adapter, decisions = setup
    value = event(1)
    target = Target(str(adapter.root), "telegram", "room-a", "", "u_1", "101", ("101",), frozenset(), 100, lambda: 50)
    value._luna_reply_target = target
    assert can_deliver(value) and reply_anchor(value) == "101"
    value.source.user_id = "different-person"
    assert not can_deliver(value)
    value.source.user_id = "u_1"
    assert not can_deliver(value, now=101)
    value._luna_reply_target = replace(target, profile_home="/another-profile")
    assert not can_deliver(value)


def test_target_changes_do_not_change_cached_agent_signature(setup):
    coordinator, adapter, decisions = setup
    from gateway.run import GatewayRunner
    target = Target(str(adapter.root), "telegram", "room-a", "", "u_1", "101", ("101",), frozenset({"102"}), 100)
    signatures = []
    for candidate in (target, replace(target, message_id="999", excluded_message_ids=frozenset({"900"}))):
        token = CURRENT_TARGET.set(candidate)
        try:
            signatures.append(GatewayRunner._agent_config_signature("model", {"provider": "custom"}, ["web", "people"], "static persona", user_id="u_1"))
        finally:
            CURRENT_TARGET.reset(token)
    assert signatures[0] == signatures[1]


@pytest.mark.parametrize("value", [{"max_pending": 0}, {"max_turns_per_burst": True}, {"enabled": "false"}, {"settle_seconds": float("nan")}])
def test_invalid_policy_is_rejected(value):
    with pytest.raises(ValueError):
        validate_policy(value)


@pytest.mark.asyncio
async def test_edit_of_active_question_interrupts_agent_and_prevents_old_answer(setup):
    from unittest.mock import AsyncMock
    coordinator, adapter, decisions = setup
    adapter.gateway_runner = SimpleNamespace(_interrupt_and_clear_session=AsyncMock())
    adapter.hold = asyncio.Event()
    original = event(1, text="original question?")
    await coordinator.submit(original)
    await until(lambda: len(adapter.started) == 1)
    await coordinator.submit(event(1, text="edited question?"))
    await idle(coordinator)
    adapter.gateway_runner._interrupt_and_clear_session.assert_awaited_once()
    assert not can_deliver(original)
    assert not adapter.sent
    assert any(reason == "edited_during_reply" for _, _, reason in decisions)


@pytest.mark.asyncio
async def test_pending_edit_replaces_old_request_without_extra_reply(setup):
    coordinator, adapter, decisions = setup
    await coordinator.submit(event(1, text="old question?"))
    await coordinator.submit(event(1, text="corrected question?"))
    await idle(coordinator)
    assert [row[-1] for row in adapter.sent] == ["corrected question?"]


@pytest.mark.asyncio
async def test_cancelled_coordinator_cancels_its_selected_child(setup):
    coordinator, adapter, decisions = setup
    adapter.hold = asyncio.Event()
    await coordinator.submit(event(1))
    await until(lambda: len(adapter.started) == 1)
    lane = next(iter(coordinator.lanes.values()))
    lane.task.cancel()
    await asyncio.gather(lane.task, return_exceptions=True)
    assert adapter.running == 0 and not adapter._session_tasks
    assert not can_deliver(adapter.started[0])
    assert not adapter.sent and coordinator.active_rooms == 0


@pytest.mark.asyncio
async def test_capacity_rejections_get_one_acknowledgement_and_stay_bounded(setup):
    coordinator, adapter, decisions = setup
    coordinator.policy = replace(coordinator.policy, max_pending=2)
    for index in range(100):
        await coordinator.submit(event(index))
    assert len(next(iter(coordinator.lanes.values())).pending) == 2
    await idle(coordinator)
    assert len(adapter.started) == 2
    assert len([row for row in adapter.sent if row[2] is None]) == 1
    assert sum(reason == "capacity" for _, _, reason in decisions) == 98


@pytest.mark.asyncio
async def test_restart_drops_known_requests_and_dashboard_reports_stopped_work(setup):
    from luna_cli.conversation_status import report
    coordinator, adapter, decisions = setup
    coordinator.record = _store
    await coordinator.submit(event(1))
    await idle(coordinator)
    restarted = Coordinator(adapter, adapter.root, coordinator.policy)
    await restarted.submit(event(1))
    assert len(adapter.started) == 1 and not any(lane.pending for lane in restarted.lanes.values())
    rows = report()["recent"]
    assert len(rows) == 1 and rows[0]["state"] == "finished"
    assert "text" not in rows[0] and "pid" not in rows[0]
    from luna_core import db
    with db.open_db(adapter.root / "luna-state.db") as conn:
        conn.execute("UPDATE conversation_intents SET state='waiting',pid=-1")
        conn.commit()
    status = report()
    assert status["waiting"] == [] and status["active"] == []
    assert status["recent"][0]["reason"] == "gateway_stopped"


@pytest.mark.asyncio
async def test_provider_failures_count_against_burst_without_flood_or_blocking_others(setup):
    coordinator, adapter, decisions = setup
    original = adapter._process
    async def limited(value, key):
        if value.source.user_id == "u_0":
            adapter._session_tasks.pop(key, None)
            raise RuntimeError("429 rate limited")
        await original(value, key)
    adapter._process = limited
    for index in range(10):
        await coordinator.submit(event(index))
    await idle(coordinator)
    assert sum(reason == "turn_failed" for _, _, reason in decisions) == 1
    assert len(adapter.started) == 2
    assert sum(reason == "burst_limit" for _, _, reason in decisions) == 7


@pytest.mark.asyncio
async def test_reply_to_bot_priority_still_gives_other_authors_a_turn(setup):
    coordinator, adapter, decisions = setup
    for index in range(5):
        value = event(index, user="loud", parent=str(index))
        value.reply_to_is_own_message = True
        await coordinator.submit(value)
    await coordinator.submit(event(10, user="quiet"))
    await idle(coordinator)
    assert [value.source.user_id for value in adapter.started] == ["loud", "loud", "quiet"]


@pytest.mark.asyncio
async def test_waiting_room_expires_while_global_capacity_is_occupied(setup):
    coordinator, adapter, decisions = setup
    coordinator.policy = replace(coordinator.policy, max_parallel_rooms=1)
    adapter.hold = asyncio.Event()
    await coordinator.submit(event(1, chat="busy"))
    await until(lambda: len(adapter.started) == 1)
    coordinator.policy = replace(coordinator.policy, max_age_seconds=0.03)
    await coordinator.submit(event(2, chat="waiting"))
    waiting = coordinator.lanes[("telegram", "waiting", "")]
    await asyncio.wait_for(waiting.task, 2)
    assert not waiting.pending and len(adapter.started) == 1
    adapter.hold.set()
    await idle(coordinator)
    assert any(reason == "expired" for _, _, reason in decisions)


@pytest.mark.asyncio
async def test_timeout_revokes_delivery_and_frees_room_capacity(setup):
    coordinator, adapter, decisions = setup
    coordinator.policy = replace(coordinator.policy, max_answer_age_seconds=0.02)
    adapter.hold = asyncio.Event()
    await coordinator.submit(event(1))
    await asyncio.wait_for(idle(coordinator), 2)
    assert adapter.running == 0 and coordinator.active_rooms == 0
    assert not adapter.sent and not can_deliver(adapter.started[0])
    assert any(reason == "answer_timeout" for _, _, reason in decisions)


@pytest.mark.asyncio
async def test_old_transport_backlog_never_starts_inference(setup):
    from datetime import datetime, timezone
    coordinator, adapter, decisions = setup
    value = event(1)
    value.timestamp = datetime.fromtimestamp(1, timezone.utc)
    await coordinator.submit(value)
    assert not adapter.started
    assert any(reason == "stale_arrival" for _, _, reason in decisions)


@pytest.mark.asyncio
async def test_minute_limit_and_late_burst_acknowledgement_are_bounded(setup):
    coordinator, adapter, decisions = setup
    now = [100.0]
    coordinator.clock = lambda: now[0]
    coordinator.policy = replace(coordinator.policy, max_turns_per_burst=1, max_turns_per_minute=2)
    await coordinator.submit(event(1))
    await idle(coordinator)
    # Still the same burst, but the first turn already finished: acknowledge the
    # newly skipped question rather than silently appearing stuck.
    await coordinator.submit(event(2))
    await idle(coordinator)
    assert len(adapter.started) == 1 and len([row for row in adapter.sent if row[2] is None]) == 1
    now[0] += 9
    await coordinator.submit(event(3))
    await idle(coordinator)
    now[0] += 9
    await coordinator.submit(event(4))
    await idle(coordinator)
    assert len(adapter.started) == 2
    assert any(reason == "room_rate_limit" for _, _, reason in decisions)
    assert len([row for row in adapter.sent if row[2] is None]) == 1
