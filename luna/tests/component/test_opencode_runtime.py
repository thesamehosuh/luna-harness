"""Run real Luna conversations/tools/finalization with native inference replaced.

No model network, Telegram poller or legacy deployment is used.
"""
from __future__ import annotations

import importlib.util
import json
from contextvars import ContextVar
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from luna_core.opencode_client import NativeResult


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LUNA_INDEX_DB", str(tmp_path / "luna-state.db"))
    calls = []
    behavior = {"text": "The native model replied.", "tool": None, "error": None}
    class Native:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def run(self, **kwargs):
            calls.append(kwargs)
            if behavior.get("missing_session") and kwargs.get("session_id"):
                from luna_core.opencode_client import SessionUnavailable
                raise SessionUnavailable("missing committed session")
            if behavior["error"]:
                raise behavior["error"]
            kwargs["on_step"]()
            if behavior["tool"]:
                name, arguments = behavior["tool"]
                behavior["tool_result"] = kwargs["dispatch"](name, arguments)
            return NativeResult(session_id="native-session", text=behavior["text"], steps=1, input_tokens=20, output_tokens=5)
    monkeypatch.setattr("luna_core.opencode_runtime.OpenCodeServer", Native)
    # Titling is an unrelated background model call, not part of these conversation tests.
    monkeypatch.setattr("agent.turn_context._maybe_title_session_at_turn_start", lambda *args: None)
    return calls, behavior


def agent(**kwargs):
    from run_agent import AIAgent
    return AIAgent(model="opencode/test-free", provider="opencode-engine", quiet_mode=True,
                   enabled_toolsets=kwargs.pop("enabled_toolsets", []), skip_memory=True,
                   skip_context_files=True, skip_background_review=True, **kwargs)


def test_real_conversation_keeps_dynamic_context_in_user_turn_and_resumes(native):
    calls, _ = native
    instance = agent()
    instance._gateway_turn_context_notes = "Room roster: transport_peer_1"
    first = instance.run_conversation("hello Luna")
    instance._gateway_turn_context_notes = "Reply chain: transport_peer_2"
    second = instance.run_conversation("a second question", conversation_history=first["messages"])
    assert first["completed"] and second["completed"]
    assert calls[0]["instructions"] == calls[1]["instructions"]
    assert "Room roster" not in calls[0]["instructions"]
    assert "Reply chain" not in calls[1]["instructions"]
    assert "Room roster: transport_peer_1" in calls[0]["prompt"]
    assert "Reply chain: transport_peer_2" in calls[1]["prompt"]
    assert calls[1]["session_id"] == "native-session"
    assert first["messages"][0]["content"] == "hello Luna"


@pytest.mark.parametrize("image", [False, True])
def test_persona_channel_prefill_recall_and_plugins_reach_native_with_durable_sidecars(native, tmp_path, monkeypatch, image):
    from agent.memory_manager import MemoryManager
    from agent.memory_provider import MemoryProvider
    from hermes_state import SessionDB

    class Recall(MemoryProvider):
        name = "builtin"
        def is_available(self): return True
        def initialize(self, *args, **kwargs): pass
        def get_tool_schemas(self): return []
        def prefetch(self, query, **kwargs):
            queries.append(query)
            return "RECALL_FROM_MEMORY_PROVIDER"
        def on_turn_start(self, *args, **kwargs):
            authors.append(kwargs.get("author_id"))

    queries, authors = [], []
    memory = MemoryManager()
    memory.add_provider(Recall())
    calls, _ = native
    (tmp_path / "SOUL.md").write_text("You are Luna. PERSONA_FROM_SOUL_FILE.\n")
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda name, **kw:
                        [{"context": "PLUGIN_USER_CONTEXT"}] if name == "pre_llm_call" else [])
    text = "Please recall what we discussed about our telescope."
    message = ([{"type": "text", "text": text}, {"type": "image_url", "image_url": {
        "url": "data:image/png;base64,c3ludGhldGlj"}}] if image else text)
    try:
        with SessionDB(tmp_path / "state.db") as db:
            instance = agent(session_id="context-session", session_db=db, load_soul_identity=True,
                ephemeral_system_prompt="CHANNEL_AND_SURFACE_POLICY", prefill_messages=[
                    {"role": "system", "content": "TRUSTED_SYSTEM_PRIMING"},
                    {"role": "developer", "content": "TRUSTED_DEVELOPER_PRIMING"},
                    {"role": "user", "content": "PREFILL_QUESTION"},
                    {"role": "assistant", "content": "PREFILL_ANSWER"}])
            instance._memory_manager = memory
            instance._gateway_turn_context_notes = "ROOM_ROSTER_AND_REPLY_CHAIN"
            first = instance.run_conversation(message, turn_author={"id": "transport-peer-1", "name": "Synthetic"})
            assert first["completed"]
            initial = calls[-1]
            assert "PERSONA_FROM_SOUL_FILE" in initial["instructions"]
            assert "CHANNEL_AND_SURFACE_POLICY" in initial["instructions"]
            for marker in ("TRUSTED_SYSTEM_PRIMING", "TRUSTED_DEVELOPER_PRIMING"):
                assert initial["instructions"].count(marker) == 1
                assert marker not in initial["prompt"]
            for marker in ("RECALL_FROM_MEMORY_PROVIDER", "PLUGIN_USER_CONTEXT", "ROOM_ROSTER_AND_REPLY_CHAIN",
                           "PREFILL_QUESTION", "PREFILL_ANSWER"):
                assert initial["prompt"].count(marker) == 1
                assert marker not in initial["instructions"]
            assert bool(initial["files"]) == image
            if image:
                from agent.turn_context import build_api_messages
                wire, _ = build_api_messages(instance, first["messages"], current_turn_user_idx=0,
                    ext_prefetch_cache="", plugin_user_context="", moa_config=None,
                    active_system_prompt=instance._cached_system_prompt)
                outgoing = next(row for row in wire if row["role"] == "user")
                assert "api_content" not in outgoing
                assert "RECALL_FROM_MEMORY_PROVIDER" in outgoing["content"][0]["text"]
                assert any(part.get("type") == "image_url" for part in outgoing["content"])
            history = db.get_messages_as_conversation("context-session")
            user = next(row for row in history if row["role"] == "user")
            assert "RECALL_FROM_MEMORY_PROVIDER" not in json.dumps(user["content"])
            assert "RECALL_FROM_MEMORY_PROVIDER" in user["api_content"]
            if image:
                # The engine deliberately stores text placeholders, while the
                # committed native session retains the original attachment.
                assert "[screenshot]" in user["content"]
                assert any(part.get("type") == "image_url" for part in first["messages"][0]["content"])
            second = instance.run_conversation("Please continue the telescope discussion.", conversation_history=history)
            assert second["completed"]
            assert calls[-1]["session_id"] == "native-session"
            assert calls[-1]["instructions"] == initial["instructions"]
            assert "ROOM_ROSTER_AND_REPLY_CHAIN" not in calls[-1]["prompt"]
            assert "PREFILL_ANSWER" not in calls[-1]["prompt"]
            assert queries[0] == text
            assert authors[0] == "transport-peer-1"
    finally:
        memory.shutdown_all()


def test_changed_channel_policy_or_prefill_reseeds_native_context(native):
    calls, _ = native
    instance = agent(ephemeral_system_prompt="ORIGINAL_CHANNEL_POLICY")
    first = instance.run_conversation("first question")
    instance.ephemeral_system_prompt = "UPDATED_CHANNEL_POLICY"
    second = instance.run_conversation("continue", conversation_history=first["messages"])
    assert second["completed"]
    assert calls[-1]["session_id"] is None
    assert "UPDATED_CHANNEL_POLICY" in calls[-1]["instructions"]
    assert "ORIGINAL_CHANNEL_POLICY" not in calls[-1]["instructions"]
    instance.prefill_messages = [{"role": "user", "content": "NEW_PRIMING_CONTEXT"}]
    third = instance.run_conversation("continue again", conversation_history=second["messages"])
    assert third["completed"] and calls[-1]["session_id"] is None
    assert "NEW_PRIMING_CONTEXT" in calls[-1]["prompt"]


@pytest.mark.parametrize("compacted", [False, True])
def test_image_sidecar_backfills_the_actual_durable_projection(native, tmp_path, compacted):
    from agent.turn_context import _stamp_api_content_sidecar
    from hermes_state import SessionDB
    with SessionDB(tmp_path / "state.db") as db:
        db.create_session("image-backfill", source="cli")
        instance = agent(session_id="image-backfill", session_db=db)
        instance._session_db_created = True
        message = {"role": "user", "content": [{"type": "text", "text": "Look at our telescope."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,c3ludGhldGlj"}}]}
        if compacted:
            db.archive_and_compact("image-backfill", [message])
            message["_row_id"] = db.get_messages("image-backfill")[-1]["id"]
        else:
            assert instance._flush_messages_to_session_db([message])
        _stamp_api_content_sidecar(instance, [message], 0, "IMAGE_RECALL", "IMAGE_PLUGIN",
                                  preflight_compressed=compacted)
        stored = db.get_messages("image-backfill")[-1]
        assert stored["api_content"] == message["api_content"]
        assert "IMAGE_RECALL" in stored["api_content"]
        assert "IMAGE_PLUGIN" in stored["api_content"]


def test_expired_confirmation_in_history_cannot_resume_native_context(native):
    calls, _ = native
    instance = agent()
    first = instance.run_conversation("yes, delete everything")
    first["messages"][0]["timestamp"] = 1
    second = instance.run_conversation("What happened earlier?", conversation_history=first["messages"])
    assert second["completed"]
    assert calls[-1]["session_id"] is None
    assert "yes, delete everything" not in calls[-1]["prompt"]


def test_restart_resumes_only_after_durable_transcript_and_binding(native, tmp_path):
    from hermes_state import SessionDB
    calls, _ = native
    with SessionDB(tmp_path / "state.db") as db:
        first_agent = agent(session_id="luna-session", session_db=db)
        first = first_agent.run_conversation("remember our conversation")
        binding = db.get_session_model_config_value("luna-session", "luna_opencode")
        assert binding["id"] == "native-session"
        second_agent = agent(session_id="luna-session", session_db=db)
        second = second_agent.run_conversation("continue", conversation_history=first["messages"])
        assert second["completed"]
        assert calls[-1]["session_id"] == "native-session"


def test_changed_history_starts_with_history_seed(native):
    calls, _ = native
    instance = agent()
    instance.run_conversation("first question")
    result = instance.run_conversation("continue", conversation_history=[{"role": "user", "content": "compressed earlier context"}])
    assert result["completed"]
    assert calls[-1]["session_id"] is None
    assert "compressed earlier context" in calls[-1]["prompt"]
    assert "compressed earlier context" not in calls[-1]["instructions"]


def test_rebuilt_native_history_does_not_trust_a_divergent_database_prefix(native, tmp_path):
    from hermes_state import SessionDB
    calls, _ = native
    with SessionDB(tmp_path / "state.db") as db:
        instance = agent(session_id="divergent-history", session_db=db)
        instance.run_conversation("old database question")
        result = instance.run_conversation("new question", conversation_history=[
            {"role": "user", "content": "replacement summary"},
            {"role": "assistant", "content": "summary acknowledged"}])
        assert result["completed"] and calls[-1]["session_id"] is None
        binding = db.get_session_model_config_value("divergent-history", "luna_opencode")
        assert "persisted_history" not in binding
        restored = db.get_messages_as_conversation("divergent-history")
        instance.run_conversation("continue from the actual database", conversation_history=restored)
        assert calls[-1]["session_id"] is None
        assert "old database question" in calls[-1]["prompt"]


def test_missing_committed_session_is_reseeded_before_any_new_tool_execution(native):
    calls, behavior = native
    instance = agent()
    first = instance.run_conversation("earlier committed question")
    behavior["missing_session"] = True
    second = instance.run_conversation("continue", conversation_history=first["messages"])
    assert second["completed"]
    assert calls[-2]["session_id"] == "native-session"
    assert calls[-1]["session_id"] is None
    assert "earlier committed question" in calls[-1]["prompt"]


def test_real_file_tool_dispatch_and_approval_context(native, tmp_path):
    from acp_adapter.edit_approval import set_edit_approval_requester, reset_edit_approval_requester
    calls, behavior = native
    file = tmp_path / "synthetic.txt"
    file.write_text("before")
    behavior["tool"] = ("write_file", {"path": str(file), "content": "after"})
    approval_context = ContextVar("native-approval-test", default=None)
    context_token = approval_context.set("owning-native-turn")
    approvals = []
    def decline(proposal):
        approvals.append((approval_context.get(), proposal.new_text))
        return False
    token = set_edit_approval_requester(decline)
    try:
        instance = agent(enabled_toolsets=["file"])
        result = instance.run_conversation("change the synthetic file")
    finally:
        reset_edit_approval_requester(token)
        approval_context.reset(context_token)
    assert result["completed"]
    assert file.read_text() == "before"
    assert approvals == [("owning-native-turn", "after")]
    assert "denied" in str(behavior["tool_result"]).lower()
    assert [row["role"] for row in result["messages"]] == ["user", "assistant", "tool", "assistant"]


def test_persistence_failure_prevents_tool_side_effect(native, tmp_path, monkeypatch):
    from hermes_state import SessionDB
    calls, behavior = native
    target = tmp_path / "must-not-exist.txt"
    behavior["tool"] = ("write_file", {"path": str(target), "content": "unsafe"})
    with SessionDB(tmp_path / "state.db") as db:
        instance = agent(session_id="persist-test", session_db=db, enabled_toolsets=["file"])
        original = instance._flush_messages_to_session_db
        def fail_tool_call(messages, *args, **kwargs):
            if messages[-1].get("tool_calls"):
                return False
            return original(messages, *args, **kwargs)
        monkeypatch.setattr(instance, "_flush_messages_to_session_db", fail_tool_call)
        result = instance.run_conversation("write a file")
    assert result["completed"] is False
    assert "not executed" in result["error"]
    assert not target.exists()


def test_native_reply_passes_real_room_output_transform(native, monkeypatch):
    calls, behavior = native
    path = Path(__file__).resolve().parents[2] / "plugins/luna-room/__init__.py"
    spec = importlib.util.spec_from_file_location("opencode_room_test", path)
    room = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(room)
    room._SESSION_SURFACE["room-session"] = {"surface": "group"}
    behavior["text"] = "\n".join(f"Line {number} with too many emoji 😀😀😀😀😀" for number in range(12))
    def hooks(name, **kwargs):
        return [room._on_transform_llm_output(**kwargs)] if name == "transform_llm_output" else []
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", hooks)
    result = agent(session_id="room-session", platform="telegram").run_conversation("say something")
    assert result["completed"]
    assert result["final_response"] != behavior["text"]
    assert len(result["final_response"].splitlines()) <= 4
    assert result["final_response"].count("😀") <= 1


@pytest.mark.parametrize("error", [RuntimeError("Free usage limit reached"), InterruptedError("stop")])
def test_native_failures_and_stop_do_not_commit_a_resumable_binding(native, error):
    calls, behavior = native
    behavior["error"] = error
    instance = agent()
    sync = Mock()
    instance._sync_external_memory_for_turn = sync
    result = instance.run_conversation("hello")
    assert result["completed"] is False
    assert result["partial"] is True
    if not isinstance(error, InterruptedError):
        sync.assert_not_called()
    assert getattr(instance, "_luna_opencode_binding", None) is None
    assert len(calls) == 1
    if isinstance(error, InterruptedError):
        assert result["interrupted"]
    else:
        assert "Free usage limit" in result["error"]


def test_auxiliary_auto_uses_native_engine_without_reading_other_keys(native, monkeypatch):
    from agent.auxiliary_client import resolve_provider_client
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unused-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-unused-key")
    runtime = {"provider": "opencode-engine", "model": "opencode/test-free", "base_url": "opencode://local", "api_key": "no-key-required", "api_mode": "chat_completions"}
    client, model = resolve_provider_client("auto", main_runtime=runtime)
    assert type(client).__name__ == "OpenCodeAuxClient"
    assert model == "opencode/test-free"
