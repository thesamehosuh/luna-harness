"""Room-level turn taking, outside cached agents and their per-person histories.

Transport-owned requests remain separate. Only the selected event enters the existing
adapter/runner path; waiting events never start typing, create agents or steer a live turn.
"""
from __future__ import annotations

import asyncio
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import hashlib
import logging
import os
from pathlib import Path
import time
import threading
import weakref

from luna_core.runtime import home
from luna_core.surface_policy import room_surface

_COORDINATORS = weakref.WeakSet()
_REGISTRY_LOCK = threading.Lock()
logger = logging.getLogger("luna-room-dispatch")


@dataclass(frozen=True)
class Policy:
    enabled: bool = True
    settle_seconds: float = 1.0
    response_gap_seconds: float = 2.0
    max_pending: int = 16
    max_age_seconds: float = 60.0
    max_answer_age_seconds: float = 120.0
    max_turns_per_burst: int = 3
    burst_idle_seconds: float = 8.0
    max_turns_per_minute: int = 6
    max_parallel_rooms: int = 4
    overload_notice: bool = True


BOUNDS = {"settle_seconds": (0, 3), "response_gap_seconds": (0, 30),
          "max_pending": (1, 64), "max_age_seconds": (5, 300),
          "max_answer_age_seconds": (15, 600), "max_turns_per_burst": (1, 10),
          "burst_idle_seconds": (2, 60), "max_turns_per_minute": (1, 30),
          "max_parallel_rooms": (1, 16)}


def validate_policy(raw):
    if not isinstance(raw, dict):
        raise ValueError("Conversation settings must be an object")
    defaults = Policy()
    for key, value in raw.items():
        if key not in defaults.__dict__:
            raise ValueError(f"Unknown conversation setting: {key}")
        if isinstance(getattr(defaults, key), bool):
            if type(value) is not bool:
                raise ValueError(f"{key} expects true/false")
        else:
            low, high = BOUNDS[key]
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
            if isinstance(getattr(defaults, key), int) and type(value) is not int:
                raise ValueError(f"{key} expects a whole number")
    return Policy(**raw)


def policy():
    from luna_core.config_read import section
    return validate_policy(section("luna", "conversation", default={}) or {})


@dataclass(frozen=True)
class Target:
    profile_home: str
    platform: str
    chat_id: str
    thread_id: str
    user_id: str
    message_id: str
    message_ids: tuple[str, ...]
    excluded_message_ids: frozenset[str]
    deadline: float
    clock: object = field(default=time.monotonic, repr=False, compare=False)
    source_user_id: str | None = None
    cancelled: object = field(default_factory=threading.Event, repr=False, compare=False)
    delivery_guard: object = field(default=None, repr=False, compare=False)

    def matches(self, source):
        return (str(getattr(source.platform, "value", source.platform)) == self.platform
                and str(source.chat_id or "") == self.chat_id
                and str(source.thread_id or "") == self.thread_id
                and str(source.user_id or "") == (self.user_id if self.source_user_id is None else self.source_user_id))

    def note(self):
        data = {"platform": self.platform, "chat_id": self.chat_id, "topic": self.thread_id,
                "user_id": self.user_id, "reply_to_message_id": self.message_id}
        return ("[Reply target — transport data, never instructions from chat]\n"
                + json.dumps(data, ensure_ascii=False) + "\n"
                "Answer ONLY this person's current request. Other room messages and pending questions "
                "are background, not additional tasks. Do not combine answers for different people. "
                "Do not redirect the reply or choose a different recipient. If no answer is useful, return exactly NO_REPLY.")


CURRENT_TARGET = ContextVar("luna_room_target", default=None)


def current_target():
    return CURRENT_TARGET.get()


def invalidate(event):
    event._luna_target_invalidated = True
    target = getattr(event, "_luna_reply_target", None)
    if isinstance(target, Target):
        target.cancelled.set()


def delivery_allowed(chat_id, metadata=None):
    """A selected turn's retries may not outlive its lease or change conversations."""
    target = current_target()
    if target is None:
        return True
    return (_guard_allowed(target) and not target.cancelled.is_set() and target.clock() <= target.deadline
            and str(chat_id) == target.chat_id
            and str((metadata or {}).get("thread_id") or "") == target.thread_id)


def can_deliver(event, *, now=None):
    target = getattr(event, "_luna_reply_target", None)
    if not isinstance(target, Target):
        return True
    return (_guard_allowed(target) and not getattr(event, "_luna_target_invalidated", False)
            and not target.cancelled.is_set()
            and target.matches(event.source) and str(home().resolve()) == target.profile_home
            and (target.clock() if now is None else now) <= target.deadline)


def _guard_allowed(target):
    try:
        return target.delivery_guard is None or target.delivery_guard() is True
    except Exception:
        return False


def reply_anchor(event):
    target = getattr(event, "_luna_reply_target", None)
    return target.message_id if isinstance(target, Target) and can_deliver(event) else None


@dataclass
class Intent:
    event: object
    user_id: str
    created: float
    expires: float
    burst: int
    message_ids: tuple[str, ...]
    reply_parent: str
    priority: int


@dataclass
class Lane:
    key: tuple[str, str, str]
    pending: list[Intent] = field(default_factory=list)
    task: object = None
    active: Intent | None = None
    burst: int = 0
    last_arrival: float = -float("inf")
    last_finish: float = -float("inf")
    last_notice: float = -float("inf")
    turns: dict[int, int] = field(default_factory=dict)
    recent_turns: deque = field(default_factory=deque)
    unanswered: dict[str, str] = field(default_factory=dict)
    last_author: str = ""
    consecutive: int = 0
    seen: dict[str, tuple[str, str]] = field(default_factory=dict)
    overloaded: bool = False


def _parent(event):
    raw = getattr(event, "raw_message", None)
    reply = getattr(raw, "reply_to_message", None)
    return str(getattr(event, "reply_to_message_id", None) or getattr(reply, "message_id", "") or "")


def _priority(adapter, event):
    raw = getattr(event, "raw_message", None)
    reply = getattr(raw, "reply_to_message", None)
    author = getattr(reply, "from_user", None)
    bot_id = getattr(getattr(adapter, "_bot", None), "id", None)
    replying_to_bot = bool(getattr(event, "reply_to_is_own_message", False)
                           or (bot_id is not None and getattr(author, "id", None) == bot_id))
    return (100 if replying_to_bot else 0) + (10 if any(c in str(event.text or "") for c in ("?", "؟")) else 0)


def _store(root, intent, state, reason):
    """Bounded metadata ledger only: no request text, tokens or model content."""
    from contextlib import closing
    from luna_core import db
    import psutil
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = intent.event.source
    with closing(db.connect(root / "luna-state.db")) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS conversation_intents (id TEXT PRIMARY KEY, platform TEXT, chat_id TEXT, thread_id TEXT, user_id TEXT, message_id TEXT, state TEXT, reason TEXT, at REAL, expires REAL, pid INTEGER, process_start REAL)")
        if "process_start" not in {row[1] for row in conn.execute("PRAGMA table_info(conversation_intents)")}:
            conn.execute("ALTER TABLE conversation_intents ADD COLUMN process_start REAL")
        if "anchor_message_id" not in {row[1] for row in conn.execute("PRAGMA table_info(conversation_intents)")}:
            conn.execute("ALTER TABLE conversation_intents ADD COLUMN anchor_message_id TEXT")
        expires = intent.expires
        target = getattr(intent.event, "_luna_reply_target", None)
        if state == "active" and isinstance(target, Target):
            expires = target.deadline
        for mid in intent.message_ids:
            key = json.dumps([str(getattr(source.platform, 'value', source.platform)), str(source.chat_id), str(source.thread_id or ''), mid])
            conn.execute("INSERT OR REPLACE INTO conversation_intents (id,platform,chat_id,thread_id,user_id,message_id,state,reason,at,expires,pid,process_start,anchor_message_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, str(getattr(source.platform, 'value', source.platform)), str(source.chat_id), str(source.thread_id or ''), intent.user_id, mid, state, reason, time.time(), time.time() + max(0, expires - time.monotonic()), os.getpid(), psutil.Process().create_time(), str(intent.event.message_id)))
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'").fetchone():
                conn.execute("UPDATE messages SET triggered=1 WHERE chat_id=? AND message_id=?", (str(source.chat_id), mid))
        conn.execute("DELETE FROM conversation_intents WHERE rowid NOT IN (SELECT rowid FROM conversation_intents ORDER BY at DESC LIMIT 1000)")


def _known(root, key, mid):
    """A restart drops waiting work; it never replays a previously admitted question."""
    import sqlite3
    from contextlib import closing
    from luna_core import db
    path = Path(root) / "luna-state.db"
    if not path.exists():
        return False
    try:
        with closing(db.connect(path, read_only=True)) as conn:
            return conn.execute("SELECT 1 FROM conversation_intents WHERE id=?", (json.dumps([*key, mid]),)).fetchone() is not None
    except sqlite3.OperationalError:
        return False


class Coordinator:
    def __init__(self, adapter, root, settings, *, clock=time.monotonic, wall_clock=time.time, sleep=asyncio.sleep, record=_store, known=_known):
        self.adapter, self.root, self.policy = adapter, str(root), settings
        self.clock, self.sleep, self.record = clock, sleep, record
        self.wall_clock, self.known = wall_clock, known
        self.lanes = {}
        self.active_rooms = 0
        self.capacity = asyncio.Condition()
        with _REGISTRY_LOCK:
            _COORDINATORS.add(self)

    def _decision(self, intent, state, reason):
        if state in {"skipped", "finished"}:
            from luna_core.wake_delivery import complete
            complete(intent.event, reason)
        try:
            self.record(self.root, intent, state, reason)
        except Exception:
            # Metrics failure cannot bypass admission or turn it into an uncaught send.
            logger.warning("Conversation decision ledger unavailable", exc_info=True)

    def _drop(self, lane, intent, reason):
        if intent in lane.pending:
            lane.pending.remove(intent)
        self._decision(intent, "skipped", reason)

    async def _cancel(self, intent, reason):
        invalidate(intent.event)
        intent.event._luna_cancel_reason = reason
        session_key = self.adapter._event_session_key(intent.event)
        runner = getattr(self.adapter, "gateway_runner", None)
        interrupt = getattr(runner, "_interrupt_and_clear_session", None)
        if callable(interrupt):
            try:
                # Cancelling asyncio alone leaves the model's executor thread alive.
                # Reuse the engine's generation-safe hard interrupt and cache eviction.
                with self.adapter._media_delivery_scope(intent.event.source):
                    await asyncio.wait_for(interrupt(session_key, intent.event.source,
                        interrupt_reason="Group reply cancelled", invalidation_reason=reason), 10)
            except Exception:
                logger.exception("Unable to interrupt the selected room agent")
        await self.adapter.cancel_session_processing(session_key, discard_pending=True)

    async def submit(self, event):
        now = self.clock()
        source = event.source
        key = (str(getattr(source.platform, "value", source.platform)), str(source.chat_id), str(source.thread_id or ""))
        # Evict only idle lanes, retaining the bounded durable receipt ledger. An
        # unbounded stream of new rooms must not leave unbounded in-memory queues.
        for old_key, old in list(self.lanes.items()):
            if len(self.lanes) < 256:
                break
            if not old.active and not old.pending and (old.task is None or old.task.done()):
                self.lanes.pop(old_key, None)
        if key not in self.lanes and len(self.lanes) >= 256:
            event._gateway_accepted = False
            return
        lane = self.lanes.setdefault(key, Lane(key))
        if now - lane.last_arrival > self.policy.burst_idle_seconds:
            lane.burst += 1
        lane.last_arrival = now
        for item in list(lane.pending):
            if item.expires <= now:
                self._drop(lane, item, "expired")
        retained_bursts = {lane.burst, *(item.burst for item in lane.pending)}
        if lane.active:
            retained_bursts.add(lane.active.burst)
        for old_burst in list(lane.turns):
            if old_burst < lane.burst - 16 and old_burst not in retained_bursts:
                lane.turns.pop(old_burst, None)
        mid = str(getattr(event, "message_id", None) or getattr(source, "message_id", None) or "")
        uid = str(getattr(source, "user_id", "") or "")
        if getattr(event, "internal", False) and mid:
            # Autonomous events may originate from a tokenless observe session.
            # The selected recipient still comes from the transport-owned index.
            from luna_core import db
            conn = db.connect(Path(self.root) / "luna-state.db")
            try:
                db.init_db(conn)
                row = conn.execute("SELECT user_id,thread_id,timestamp FROM messages WHERE chat_id=? AND message_id=?", (str(source.chat_id), mid)).fetchone()
                if row is None or str(row["thread_id"] or "") != str(source.thread_id or ""):
                    event._gateway_accepted = False
                    return
                uid = str(row["user_id"] or "")
                from datetime import datetime, timezone
                try:
                    event.timestamp = datetime.fromisoformat(row["timestamp"])
                    if event.timestamp.tzinfo is None:
                        event.timestamp = event.timestamp.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    event._gateway_accepted = False
                    return
            finally:
                conn.close()
        if not mid or not uid:
            event._gateway_accepted = False
            return
        event.message_id = mid
        fingerprint = (uid, hashlib.sha256(str(event.text or "").encode()).hexdigest())
        if mid in lane.seen:
            # Duplicate transport delivery never creates another model turn. Edits to a
            # still-pending question replace it; edits after delivery do not replay it.
            waiting = next((item for item in lane.pending if mid in item.message_ids and item.user_id == uid), None)
            if waiting is not None and lane.seen[mid] != fingerprint:
                self._drop(lane, waiting, "edited_before_reply")
            elif lane.active and mid in lane.active.message_ids and lane.seen[mid] != fingerprint:
                # The running model saw the old request. Never let it answer that
                # obsolete version, and never silently start a second answer.
                lane.seen[mid] = fingerprint
                await self._cancel(lane.active, "edited_during_reply")
                event._gateway_accepted = True
                return
            else:
                event._gateway_accepted = not getattr(event, "internal", False)
                return
        elif self.known(self.root, key, mid):
            event._gateway_accepted = not getattr(event, "internal", False)
            return
        lane.seen[mid] = fingerprint
        while len(lane.seen) > 512:
            lane.seen.pop(next(iter(lane.seen)))
        if lane.active and mid in lane.active.message_ids:
            event._gateway_accepted = True
            return
        intent = Intent(event, uid, now, now + self.policy.max_age_seconds, lane.burst, (mid,), _parent(event), _priority(self.adapter, event))
        stamp = getattr(event, "timestamp", None)
        if stamp is not None:
            age = max(0, self.wall_clock() - stamp.timestamp())
            if age >= self.policy.max_age_seconds:
                self._decision(intent, "skipped", "stale_arrival")
                event._gateway_accepted = not getattr(event, "internal", False)
                return
            intent.expires -= age
        if lane.active and getattr(lane.active.event, "internal", False) and not getattr(event, "internal", False):
            await self._cancel(lane.active, "human_request_arrived")
        # Only fragments from one transport author AND reply chain may share an intent.
        existing = next((item for item in lane.pending if item.user_id == uid and item.reply_parent == intent.reply_parent and now - item.created <= self.policy.settle_seconds), None)
        if existing is not None and not event.media_urls and not existing.event.media_urls:
            combined = str(existing.event.text or "") + "\n" + str(event.text or "")
            if len(combined) <= 4000:
                event.text = combined
                intent.created, intent.expires = existing.created, existing.expires
                intent.message_ids = (*existing.message_ids, mid)
                self._drop(lane, existing, "combined_same_author")
        lane.unanswered[mid] = uid
        while len(lane.unanswered) > 256:
            lane.unanswered.pop(next(iter(lane.unanswered)))
        if len(lane.pending) >= self.policy.max_pending:
            lane.overloaded = True
            # Keep explicit follow-ups/questions in preference to an older low-priority mention.
            weakest = min(lane.pending, key=lambda item: (item.priority, -item.created))
            if intent.priority > weakest.priority:
                self._drop(lane, weakest, "capacity")
            else:
                self._decision(intent, "skipped", "capacity")
                event._gateway_accepted = True
                return
        lane.pending.append(intent)
        # Only identity/message ids live here; request bodies stay in the transport/index.
        self._decision(intent, "waiting", "burst_settle" if lane.active is None else "room_busy")
        event._gateway_accepted = True
        if lane.task is None or lane.task.done():
            lane.task = asyncio.create_task(self._drain(lane))
            self.adapter._background_tasks.add(lane.task)
            lane.task.add_done_callback(self.adapter._background_tasks.discard)
            lane.task.add_done_callback(self._task_done)

    @staticmethod
    def _task_done(task):
        if not task.cancelled() and task.exception() is not None:
            logger.error("Room coordinator failed", exc_info=task.exception())

    async def _notice(self, lane, event):
        if not self.policy.overload_notice or self.clock() - lane.last_notice < 60:
            return
        lane.last_notice = self.clock()
        from gateway.platforms.base import _thread_metadata_for_event
        try:
            with self.adapter._media_delivery_scope(event.source):
                await self.adapter.send(chat_id=event.source.chat_id,
                    content="A few messages came in at once. Please tag me again if I missed your question.",
                    metadata=_thread_metadata_for_event(event))
        except Exception:
            logger.debug("Overload acknowledgement was not delivered", exc_info=True)

    async def _drain(self, lane):
        try:
            await self.sleep(self.policy.settle_seconds)
            while lane.pending:
                now = self.clock()
                last_event = lane.pending[-1].event
                for item in list(lane.pending):
                    if item.expires <= now:
                        self._drop(lane, item, "expired")
                    elif lane.turns.get(item.burst, 0) >= self.policy.max_turns_per_burst:
                        self._drop(lane, item, "burst_limit")
                        lane.overloaded = True
                if not lane.pending:
                    if lane.overloaded:
                        await self._notice(lane, last_event)
                        lane.overloaded = False
                    return
                while lane.recent_turns and lane.recent_turns[0] <= now - 60:
                    lane.recent_turns.popleft()
                if len(lane.recent_turns) >= self.policy.max_turns_per_minute:
                    last = lane.pending[-1].event
                    for item in list(lane.pending):
                        self._drop(lane, item, "room_rate_limit")
                    await self._notice(lane, last)
                    return
                wait = self.policy.response_gap_seconds - (now - lane.last_finish)
                if wait > 0:
                    await self.sleep(wait)
                    continue
                async with self.capacity:
                    try:
                        await asyncio.wait_for(self.capacity.wait_for(lambda: self.active_rooms < self.policy.max_parallel_rooms),
                                               max(0.001, min(item.expires for item in lane.pending) - self.clock()))
                    except asyncio.TimeoutError:
                        continue
                    self.active_rooms += 1
                item = None
                try:
                    now = self.clock()
                    for candidate in list(lane.pending):
                        if candidate.expires <= now:
                            self._drop(lane, candidate, "expired")
                    if not lane.pending:
                        continue
                    # Avoid one author taking every slot, while preserving meaningful reply priority.
                    choices = lane.pending
                    if lane.consecutive >= 2:
                        other_authors = [candidate for candidate in choices if candidate.user_id != lane.last_author]
                        choices = other_authors or choices
                    item = max(choices, key=lambda candidate: (candidate.priority, -candidate.created))
                    lane.pending.remove(item)
                    lane.active = item
                    lane.turns[item.burst] = lane.turns.get(item.burst, 0) + 1
                    lane.recent_turns.append(now)
                    from luna_core.wake_delivery import allowed as wake_allowed
                    target = Target(self.root, *lane.key, item.user_id, str(item.event.message_id), item.message_ids,
                                    frozenset(mid for mid, author in lane.unanswered.items() if author != item.user_id),
                                    now + self.policy.max_answer_age_seconds, self.clock,
                                    str(item.event.source.user_id or ""),
                                    delivery_guard=lambda event=item.event: wake_allowed(event))
                    item.event._luna_reply_target = target
                    token = CURRENT_TARGET.set(target)
                    try:
                        self._decision(item, "active", "reply_to_bot" if item.priority >= 100 else "selected")
                        session_key = self.adapter._event_session_key(item.event)
                        previous = self.adapter._session_tasks.get(session_key)
                        if previous is not None and not previous.done():
                            try:
                                await asyncio.wait_for(asyncio.shield(previous), max(0.001, item.expires - self.clock()))
                            except (asyncio.TimeoutError, asyncio.CancelledError):
                                if asyncio.current_task().cancelling():
                                    invalidate(item.event)
                                    self._decision(item, "skipped", "shutdown")
                                    raise
                                self._decision(item, "skipped", "session_busy")
                                continue
                        if self.clock() >= item.expires:
                            self._decision(item, "skipped", "expired")
                            continue
                        if not self.adapter._start_session_processing(item.event, session_key):
                            self._decision(item, "skipped", "dispatch_failed")
                            continue
                        task = self.adapter._session_tasks[session_key]
                        try:
                            await asyncio.wait_for(asyncio.shield(task), self.policy.max_answer_age_seconds)
                        except asyncio.TimeoutError:
                            await self._cancel(item, "answer_timeout")
                            self._decision(item, "skipped", "answer_timeout")
                        except asyncio.CancelledError:
                            if asyncio.current_task().cancelling():
                                await self._cancel(item, "shutdown")
                                self._decision(item, "skipped", "shutdown")
                                raise
                            self._decision(item, "skipped", getattr(item.event, "_luna_cancel_reason", "edited_during_reply" if getattr(item.event, "_luna_target_invalidated", False) else "cancelled"))
                        except Exception:
                            self._decision(item, "skipped", "turn_failed")
                            logger.exception("Selected room turn failed")
                        else:
                            reason = getattr(item.event, "_luna_delivery_status", "turn_complete")
                            if getattr(item.event, "_luna_target_invalidated", False):
                                self._decision(item, "skipped", "edited_during_reply")
                            else:
                                self._decision(item, "finished", reason)
                        for mid in item.message_ids:
                            lane.unanswered.pop(mid, None)
                    finally:
                        CURRENT_TARGET.reset(token)
                    lane.consecutive = lane.consecutive + 1 if lane.last_author == item.user_id else 1
                    lane.last_author = item.user_id
                    lane.last_finish = self.clock()
                    exhausted = [candidate for candidate in lane.pending if lane.turns.get(candidate.burst, 0) >= self.policy.max_turns_per_burst]
                    if exhausted:
                        for candidate in exhausted:
                            self._drop(lane, candidate, "burst_limit")
                        lane.overloaded = True
                    if lane.overloaded:
                        await self._notice(lane, item.event)
                        lane.overloaded = False
                finally:
                    lane.active = None
                    async with self.capacity:
                        self.active_rooms -= 1
                        self.capacity.notify_all()
        finally:
            if lane.active:
                invalidate(lane.active.event)
            for item in list(lane.pending):
                self._drop(lane, item, "shutdown")
            lane.active = None
            lane.turns = dict(list(lane.turns.items())[-16:])


async def maybe_admit(adapter, event):
    """Called after canonical routing, before per-session merging/typing/task creation."""
    if not room_surface(getattr(event.source, "chat_type", "")):
        return False
    if getattr(adapter, "_authorization_check", None) is None:
        return False  # Legacy/unwired adapters still pass the runner's own authorization gate.
    source = event.source
    authorized = adapter._is_sender_authorized(source.user_id, source.chat_type, source.chat_id, thread_id=source.thread_id, is_bot=bool(getattr(source, "is_bot", False)))
    if authorized is not True and not getattr(event, "internal", False):
        return False
    with adapter._media_delivery_scope(source):
        settings = policy()
        if not settings.enabled:
            return False
        root = str(home().resolve())
        controllers = adapter.__dict__.setdefault("_luna_room_coordinators", {})
        controller = controllers.get(root)
        if controller is None:
            controller = controllers[root] = Coordinator(adapter, root, settings)
        controller.policy = settings
        key = (str(getattr(source.platform, "value", source.platform)), str(source.chat_id), str(source.thread_id or ""))
        lane = controller.lanes.get(key)
        if event.allow_gateway_control and event.get_command():
            command = event.get_command()
            from hermes_cli.commands import should_bypass_active_session
            if should_bypass_active_session(command):
                if lane and command in {"stop", "new", "reset", "undo"}:
                    from gateway.slash_access import policy_from_extra
                    access = policy_from_extra(adapter.config.extra, "group", require_admin=True)
                    if access.can_run(source.user_id, command):
                        for item in list(lane.pending):
                            if item.user_id == str(source.user_id):
                                controller._drop(lane, item, "cancelled_by_user")
                        if lane.active and lane.active.user_id != str(source.user_id) and not access.is_admin(source.user_id):
                            event._gateway_accepted = False
                            return True
                        if lane.active and lane.active.user_id == str(source.user_id):
                            invalidate(lane.active.event)
                return False
        if getattr(event, "internal", False):
            # Ambient/background injections cannot compete with a human conversation.
            if lane and (lane.active or lane.pending):
                event._gateway_accepted = False
                return True
        await controller.submit(event)
        return True


def room_busy(chat_id, thread_id=None):
    """Check before spending an ambient judgment; admission rechecks on the event loop."""
    root = str(home().resolve())
    with _REGISTRY_LOCK:
        controllers = list(_COORDINATORS)
    for controller in controllers:
        if controller.root != root:
            continue
        for lane in list(controller.lanes.values()):
            if lane.key[1] == str(chat_id) and (thread_id is None or lane.key[2] == str(thread_id)) and (lane.active or lane.pending):
                return True
    return False
