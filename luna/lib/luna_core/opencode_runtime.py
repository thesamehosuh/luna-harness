# SPDX-License-Identifier: Apache-2.0
# Attribution and inherited MIT notices: OPENCODE_NOTICES.txt
"""Luna conversation integration for the native OpenCode engine.

The ordinary turn prologue and finalizer still own memory, persistence and
surface transforms. MCP calls use the ordinary Luna tool executor on the
owning conversation thread, including all lifecycle hooks and approval guards.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import uuid
from types import SimpleNamespace

from luna_core.opencode_bridge import ToolBridge
from luna_core.opencode_attachments import prompt_parts
from luna_core.opencode_client import OpenCodeServer, SessionUnavailable

logger = logging.getLogger(__name__)
BINDING_KEY = "luna_opencode"
POLICY = """Your configured persona, memory and surface instructions above take precedence.
Use only the Luna MCP tools supplied for this conversation. Native OpenCode
filesystem, shell, agents and forms are unavailable. Do not repeat a declined
tool through another tool. Give the user the answer in the configured companion voice.
"""


def wire_messages(messages: list[dict]) -> list[dict]:
    """Stable digest/history seed; per-turn recall stays in its USER sidecar."""
    from agent.turn_context import substitute_api_content
    rows = []
    for message in messages:
        if message.get("role") == "system":
            continue
        row = {key: message[key] for key in ("role", "content", "name", "tool_calls", "tool_call_id") if key in message}
        if "api_content" in message:
            row["api_content"] = message["api_content"]
            substitute_api_content(row)
        rows.append(row)
    return rows


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _binding(agent):
    db, session = getattr(agent, "_session_db", None), getattr(agent, "session_id", None)
    if db is not None and session:
        return db.get_session_model_config_value(session, BINDING_KEY)
    return getattr(agent, "_luna_opencode_binding", None)


def _store_binding(agent, binding):
    agent._luna_opencode_binding = binding
    db, session = getattr(agent, "_session_db", None), getattr(agent, "session_id", None)
    if db is not None and session:
        db.patch_session_model_config(session, {BINDING_KEY: binding})


def _dispatch(agent, state, name: str, arguments: dict) -> dict:
    from agent.message_metadata import append_message
    from agent.tool_executor import execute_tool_calls_sequential
    if name not in agent.valid_tool_names or agent._interrupt_requested:
        return ToolBridge.denied()
    call_id = "luna_oc_" + uuid.uuid4().hex
    encoded = json.dumps(arguments, ensure_ascii=True)
    call = {"id": call_id, "type": "function", "function": {"name": name, "arguments": encoded}}
    append_message(state.messages, {"role": "assistant", "content": None, "tool_calls": [call]})
    # The canonical transcript must be durable BEFORE any side effect, like the generic loop.
    if agent._flush_messages_to_session_db(state.messages, state.conversation_history) is False:
        raise RuntimeError("Luna could not persist this tool call; it was not executed.")
    parsed = SimpleNamespace(id=call_id, type="function", function=SimpleNamespace(name=name, arguments=encoded))
    before = len(state.messages)
    execute_tool_calls_sequential(agent, SimpleNamespace(tool_calls=[parsed]), state.messages,
                                  state.effective_task_id, state.api_call_count, finalize=False)
    if getattr(agent, "_incremental_persistence_failed", False):
        raise RuntimeError("Luna could not persist the tool result; the native turn was stopped.")
    result = next((row for row in state.messages[before:] if row.get("role") == "tool" and row.get("tool_call_id") == call_id), None)
    if result is None:
        raise RuntimeError("Luna's tool dispatcher returned no result; the native turn was stopped.")
    content = result.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=True)
    return {"content": [{"type": "text", "text": content}]}


def _prompt(rows, *, history=False):
    latest = rows[-1] if rows else {}
    if latest.get("role") != "user":
        raise RuntimeError("OpenCode expected an admitted user turn.")
    content, files = prompt_parts(latest.get("content", ""))
    if history and rows[:-1]:
        seed = []
        for row in rows[:-1]:
            row = dict(row)
            if isinstance(row.get("content"), list):
                row["content"], previous_files = prompt_parts(row["content"])
                files.extend(previous_files)
            seed.append(row)
        content = "Previous conversation (quoted JSON):\n" + json.dumps(seed, ensure_ascii=True) + "\n\nCurrent user message:\n" + content
    return content, files


def _run_native(agent, state):
    from hermes_cli.config import load_config
    from agent.replay_cleanup import canonicalize_replay_history
    split = state.current_turn_user_idx
    history = canonicalize_replay_history(state.messages[:split], now=agent._current_turn_timestamp)
    rows = wire_messages(history + state.messages[split:])
    instructions = state.active_system_prompt or ""
    if agent.ephemeral_system_prompt:
        instructions = (instructions + "\n\n" + agent.ephemeral_system_prompt).strip()
    priming = agent.prefill_messages or []
    for message in priming:
        if message.get("role") in {"system", "developer"}:
            text, attachments = prompt_parts(message.get("content", ""))
            if attachments:
                raise ValueError("OpenCode system priming cannot contain image attachments.")
            instructions += "\n\n" + text
    instructions += "\n\n" + POLICY
    prefill = wire_messages([message for message in priming if message.get("role") not in {"system", "developer"}])
    composition = digest({"instructions": instructions, "model": agent.model, "tools": agent.tools,
                          "prefill": prefill})
    binding = _binding(agent)
    resumable = (isinstance(binding, dict) and binding.get("composition") == composition
                 and digest(rows[:-1]) in {binding.get("history"), binding.get("persisted_history")})
    native_id = binding.get("id") if resumable else None
    content, files = _prompt(prefill + rows if native_id is None else rows, history=native_id is None)
    timeout = float(((load_config().get("luna") or {}).get("opencode") or {}).get("timeout_seconds", 180))
    _store_binding(agent, None)  # An interrupted/crashed turn must not be resumed as a committed turn.

    def on_step():
        state.api_call_count += 1
        return agent.iteration_budget.consume()

    bridge = ToolBridge(agent.tools)
    try:
        with OpenCodeServer(workspace_key=str(agent.session_id or state.effective_task_id), bridge=bridge) as server:
            arguments = dict(model=agent.model, prompt=content, instructions=instructions, session_id=native_id,
                bridge=bridge, dispatch=lambda name, args: _dispatch(agent, state, name, args),
                interrupted=lambda: bool(agent._interrupt_requested), timeout=max(30, min(timeout, 1800)),
                max_steps=agent.max_iterations, on_step=on_step, files=files)
            try:
                native = server.run(**arguments)
            except SessionUnavailable:
                # This exception can only occur before a prompt is submitted. A missing/moved
                # committed native record is recoverable from Luna's durable transcript.
                content, files = _prompt(prefill + rows, history=True)
                native = server.run(**{**arguments, "session_id": None, "prompt": content, "files": files})
        return native, composition
    finally:
        bridge.close()


def run_turn(agent, state):
    from agent.turn_finalizer import finalize_turn
    native, composition, error = None, None, None
    try:
        native, composition = _run_native(agent, state)
        if not native.text.strip():
            raise RuntimeError("The free model finished without a reply. Try another free model in Setup.")
        from luna_core.runtime import home
        from luna_core.settings import _replace
        from datetime import datetime, timezone
        _replace(home() / ".native-status.json", json.dumps({"at": datetime.now(timezone.utc).isoformat(), "compacted": native.compacted,
                 "input_tokens": native.input_tokens, "output_tokens": native.output_tokens, "cost": native.cost}))
        state.final_response = native.text
        state._turn_exit_reason = "text_response(opencode_engine)"
        agent.session_input_tokens += int(native.input_tokens)
        agent.session_output_tokens += int(native.output_tokens)
        agent.session_cache_read_tokens += int(native.cached_tokens)
        agent.session_prompt_tokens += int(native.input_tokens)
        agent.session_completion_tokens += int(native.output_tokens)
        agent.session_total_tokens += int(native.input_tokens + native.output_tokens)
        agent._last_turn_usage = {"input_tokens": native.input_tokens, "output_tokens": native.output_tokens,
                                  "cache_read_tokens": native.cached_tokens}
    except InterruptedError:
        state.interrupted = True
        state.final_response = ""
        state._turn_exit_reason = "interrupted"
    except Exception as exc:
        logger.warning("OpenCode engine turn failed: %s", exc)
        error = str(exc)
        state.failed = True
        state.final_response = f"OpenCode: {exc}"
        state._turn_exit_reason = "opencode_engine_error"
    # Use the same cleanup, memory sync, room output shaping and persistence as every Luna turn.
    result = finalize_turn(agent, **{name: getattr(state, name) for name in inspect.signature(finalize_turn).parameters if name != "agent"})
    if error:
        result["error"] = error
    result["partial"] = not bool(result.get("completed"))
    if native and result.get("completed") and not result.get("cleanup_errors"):
        try:
            binding = {"id": native.session_id, "composition": composition,
                       "history": digest(wire_messages(result["messages"]))}
            # SQLite deliberately projects images to text placeholders. Pin that
            # exact durable view too, so a restart can retain the native session's
            # original attachments without accepting an edited transcript.
            db = getattr(agent, "_session_db", None)
            if db is not None and agent.session_id:
                from agent.session_persistence import _durable_content
                persisted = db.get_messages_as_conversation(agent.session_id)
                projected = [{**row, "content": _durable_content(row.get("content"))}
                             for row in result["messages"]]
                persisted_digest = digest(wire_messages(persisted))
                if persisted_digest == digest(wire_messages(projected)):
                    binding["persisted_history"] = persisted_digest
            _store_binding(agent, binding)
        except Exception:
            logger.warning("OpenCode session binding could not be persisted", exc_info=True)
    return result


