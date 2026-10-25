"""Real adapter ingress/delivery with a fake transport, including shared forum topics."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.event import MessageEvent
from gateway.session import SessionSource
from luna_core.room_dispatch import CURRENT_TARGET, Policy, Target, current_target, invalidate


class Transport(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True, extra={"thread_sessions_per_user": False}), Platform.TELEGRAM)
        self.sent, self.typing = [], []
        self.set_authorization_check(lambda *args, **kwargs: True)

    async def connect(self, **kwargs):
        return True

    async def disconnect(self):
        pass

    async def get_chat_info(self, chat_id):
        return {"id": chat_id}

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append((chat_id, reply_to, metadata, content))
        return SendResult(success=True, message_id=str(len(self.sent)))

    async def send_typing(self, chat_id, metadata=None):
        self.typing.append((chat_id, metadata))


def incoming(index, *, chat_type="forum", thread="55"):
    return MessageEvent(text=f"question {index}?", message_id=str(index), source=SessionSource(
        platform=Platform.TELEGRAM, chat_id="room", chat_type=chat_type, thread_id=thread, user_id=f"user-{index}"))


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    from luna_core import room_dispatch
    monkeypatch.setattr(room_dispatch, "policy", lambda: replace(Policy(), settle_seconds=0, response_gap_seconds=0))
    return tmp_path


async def complete(adapter):
    async def drain():
        while adapter._background_tasks:
            await asyncio.gather(*list(adapter._background_tasks))
    await asyncio.wait_for(drain(), 10)


@pytest.mark.asyncio
async def test_ten_authors_in_shared_topic_get_three_pinned_finals_without_cross_author_merge(environment):
    adapter = Transport()
    started, targets = [], []
    async def handler(event):
        started.append(event)
        targets.append(current_target())
        await asyncio.sleep(0)
        return f"answer for {event.source.user_id}"
    adapter.set_message_handler(handler)
    for index in range(10):
        await adapter.handle_message(incoming(index))
    await complete(adapter)
    answers = [row for row in adapter.sent if row[1] is not None]
    assert len(started) == len(answers) == 3
    assert len(adapter.sent) == 4  # one acknowledgement
    assert {row[1] for row in answers} == {"0", "1", "2"}
    assert all(row[2]["thread_id"] == "55" for row in answers)
    assert all(event.text == f"question {event.message_id}?" for event in started)
    assert all(target.user_id == event.source.user_id for target, event in zip(targets, started))
    assert not adapter._active_sessions and not adapter._pending_messages
    assert current_target() is None


@pytest.mark.asyncio
async def test_dm_does_not_wait_behind_busy_group_and_does_not_inherit_its_target(environment):
    adapter = Transport()
    group_started, release, dm_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def handler(event):
        if event.source.chat_type == "dm":
            assert current_target() is None
            dm_done.set()
            return "DM answer"
        assert current_target().user_id == event.source.user_id
        group_started.set()
        await release.wait()
        return "Group answer"
    adapter.set_message_handler(handler)
    await adapter.handle_message(incoming(1))
    await asyncio.wait_for(group_started.wait(), 5)
    dm = incoming(2, chat_type="dm", thread=None)
    await adapter.handle_message(dm)
    await asyncio.wait_for(dm_done.wait(), 5)
    release.set()
    await complete(adapter)
    assert {row[-1] for row in adapter.sent} == {"DM answer", "Group answer"}


@pytest.mark.asyncio
async def test_silence_is_not_sent_as_text(environment):
    adapter = Transport()
    adapter.set_message_handler(AsyncMock(return_value="NO_REPLY"))
    await adapter.handle_message(incoming(1))
    await complete(adapter)
    assert not adapter.sent


@pytest.mark.asyncio
async def test_group_obligation_is_not_replayed_by_generic_ledger_and_expired_media_is_suppressed(environment):
    adapter = Transport()
    event = incoming(1)
    event._luna_reply_target = Target(str(environment), "telegram", "room", "55", "user-1", "1", ("1",), frozenset(), 999, lambda: 1)
    assert await adapter._record_delivery_obligation(event, "session", "answer", adapter, False) is None
    invalidate(event)
    token = CURRENT_TARGET.set(event._luna_reply_target)
    try:
        result, _ = await adapter.send_final_ledgered(event, "session", "late", {"thread_id": "55"}, reply_to="1")
        assert result.success is False
        assert await adapter._play_tts_file(event, "late", "unused", True, {"thread_id": "55"}, lambda _: None) is False
        await adapter._send_image_batch(event, [("unused", "")], {"thread_id": "55"}, 0, lambda _: None)
        assert not adapter.sent
    finally:
        CURRENT_TARGET.reset(token)


@pytest.mark.asyncio
async def test_send_retry_obeys_target_expiry_and_never_redelivers_elsewhere(environment, monkeypatch):
    adapter = Transport()
    now = [1]
    target = Target(str(environment), "telegram", "room", "55", "user-1", "1", ("1",), frozenset(), 10, lambda: now[0])
    token = CURRENT_TARGET.set(target)
    calls = []
    async def send(**kwargs):
        calls.append(kwargs)
        now[0] = 11
        return SendResult(success=False, retryable=True, error="Network connection failed")
    adapter.send = send
    async def delay(_):
        pass
    monkeypatch.setattr("gateway.platforms.base.asyncio.sleep", delay)
    try:
        result = await adapter._send_with_retry("room", "answer", reply_to="1", metadata={"thread_id": "55"}, base_delay=0)
        assert result.success is False and len(calls) == 1
        result = await adapter._send_with_retry("another-room", "answer", metadata={"thread_id": "55"})
        assert result.success is False and len(calls) == 1
    finally:
        CURRENT_TARGET.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('late_error', [False, True])
@pytest.mark.parametrize('response,success,expected', [('answer', True, 'delivered'), ('answer', False, 'delivery_failed'), ('NO_REPLY', True, 'no_reply')])
async def test_wake_receipt_tracks_actual_transport_result(environment, response, success, expected, late_error):
    from datetime import datetime, timezone
    from luna_core import db
    from luna_core.room import record_inbound
    conn = db.connect(environment / 'luna-state.db')
    db.init_db(conn)
    record_inbound(conn, message_id='1', chat_id='room', thread_id='55', user_id='user-1',
                   content='synthetic question', timestamp=datetime.now(timezone.utc).isoformat())
    conn.close()
    adapter = Transport()
    receipts = []
    event = incoming(1)
    event.internal = True
    event.metadata = {'luna_delivery': {'allowed': lambda: True,
                     'complete': lambda *args: receipts.append(args)}}
    adapter.set_message_handler(AsyncMock(return_value=response))
    if not success:
        async def failed(**kwargs):
            return SendResult(success=False, error='Synthetic permanent rejection')
        adapter.send = failed
    if late_error:
        adapter._flush_text_debounce_now = AsyncMock(side_effect=[RuntimeError("synthetic post-send failure"), None])
    await adapter.handle_message(event)
    await complete(adapter)
    if late_error and expected != "delivered":
        expected = "turn_failed"
    assert receipts[0][0] == expected
    if expected == 'delivered':
        assert receipts[0][1:] == ('answer', '1')
    else:
        assert receipts[0][1:] == ('', '')


@pytest.mark.asyncio
async def test_off_during_send_retry_cancels_the_next_transport_attempt(environment, monkeypatch):
    adapter = Transport()
    enabled = [True]
    target = Target(str(environment), 'telegram', 'room', '55', 'user-1', '1', ('1',), frozenset(),
                    999, lambda: 1, delivery_guard=lambda: enabled[0])
    calls = []
    async def send(**kwargs):
        calls.append(kwargs)
        enabled[0] = False
        return SendResult(success=False, retryable=True, error='Network connection failed')
    adapter.send = send
    async def delay(_):
        pass
    monkeypatch.setattr('gateway.platforms.base.asyncio.sleep', delay)
    token = CURRENT_TARGET.set(target)
    try:
        result = await adapter._send_with_retry('room', 'answer', metadata={'thread_id': '55'}, base_delay=0)
    finally:
        CURRENT_TARGET.reset(token)
    assert not result.success and len(calls) == 1
