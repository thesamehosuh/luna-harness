"""Exact, idle-only shared-room reset through the owning gateway's local control socket.

The socket's existing owner-only filesystem/pipe permissions are the administration
boundary. No chat sender can invoke this operation. A session-id precondition makes
retries safe after a client timeout: the old request cannot reset a newer session.
"""
from __future__ import annotations

import asyncio
import concurrent.futures


async def reset_room_session(runner, params):
    key = params.get("session_key")
    expected = params.get("expected_session_id")
    if not isinstance(key, str) or not key or len(key) > 1024:
        return {"reset": False, "reason": "invalid_session_key"}
    if not isinstance(expected, str) or not expected or len(expected) > 256:
        return {"reset": False, "reason": "expected_session_id_required"}
    if not getattr(runner, "_running", False) or getattr(runner, "_draining", False):
        return {"reset": False, "reason": "gateway_stopping"}
    resetting = getattr(runner, "_room_reset_keys", None)
    if resetting is None:
        resetting = runner._room_reset_keys = set()
    if key in resetting:
        return {"reset": False, "reason": "busy"}
    # All changes and guards run on the gateway event loop. No await between the
    # final busy check and installing this barrier; ingress rechecks before claim.
    entry = await runner.async_session_store.lookup_by_session_key(key)
    if entry is None or entry.origin is None:
        return {"reset": False, "reason": "session_not_found"}
    from gateway.session_identity import replace_source
    source = replace_source(entry.origin, user_id=None, user_name=None)
    if source.chat_type not in {"group", "supergroup", "channel"} or runner._session_key_for_source(source) != key:
        return {"reset": False, "reason": "not_a_shared_room"}
    if entry.session_id != expected:
        return {"reset": False, "reason": "session_changed", "current_session_id": entry.session_id}
    adapter = runner._delivery_adapter_for(source)
    busy = runner._is_session_running(key) or key in resetting
    if adapter is not None:
        busy = busy or key in getattr(adapter, "_active_sessions", {})
        busy = busy or bool(getattr(adapter, "_pending_messages", {}).get(key))
    if busy:
        return {"reset": False, "reason": "busy"}
    resetting.add(key)
    try:
        from gateway.platforms.event import MessageEvent, MessageType
        with runner._profile_scope_for_source(source):
            current = runner.session_store.lookup_by_session_key(key)
            if current is None or current.session_id != expected:
                return {"reset": False, "reason": "session_changed"}
            # Reuse the actual /new lifecycle: cache eviction, generation fencing,
            # conversation-state cleanup, route rotation and provider/plugin hooks.
            event = MessageEvent(text="/new", source=source, message_type=MessageType.TEXT)
            await runner._handle_reset_command(event)
            fresh = await runner.async_session_store.lookup_by_session_key(key)
            db = runner.session_store._db_for_key(key)
            old_row = db.get_session(expected) if db else None
            new_row = db.get_session(fresh.session_id) if db and fresh else None
            if (fresh is None or fresh.session_id == expected or not old_row or not new_row
                    or old_row.get("end_reason") != "session_reset"
                    or new_row.get("parent_session_id") != expected):
                raise RuntimeError("Room reset persistence could not be verified; inspect the session before retrying")
        return {"reset": True, "session_key": key, "old_session_id": expected,
                "new_session_id": fresh.session_id, "history_preserved": True}
    finally:
        resetting.discard(key)


def room_control_verbs(runner):
    """Marshal local administration onto the gateway's owning event loop."""
    loop = asyncio.get_running_loop()

    async def list_rooms(params):
        from gateway.session_identity import replace_source
        rooms = []
        for entry in runner.session_store.list_sessions():
            if entry.origin is None or entry.origin.chat_type not in {"group", "supergroup", "channel"}:
                continue
            source = replace_source(entry.origin, user_id=None, user_name=None)
            if runner._session_key_for_source(source) != entry.session_key:
                continue
            rooms.append({"session_key": entry.session_key, "session_id": entry.session_id,
                          "name": entry.display_name or "", "platform": source.platform.value,
                          "chat_id": source.chat_id, "thread_id": source.thread_id,
                          "profile": source.profile or "default"})
        return {"rooms": rooms}

    def marshal(operation):
        def handler(params):
            future = asyncio.run_coroutine_threadsafe(operation(runner, params), loop)
            try:
                return future.result(timeout=60)
            except concurrent.futures.TimeoutError:
                # Do not cancel a partially completed boundary. The required old
                # id makes retries harmless once this operation finishes.
                return {"reset": False, "reason": "pending", "detail": "Check the current session before retrying"}
        return handler

    async def listing(runner, params):
        return await list_rooms(params)

    return {"reset-room-session": marshal(reset_room_session), "list-room-sessions": marshal(listing)}
