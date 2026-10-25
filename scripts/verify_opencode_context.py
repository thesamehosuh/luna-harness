"""Inspect real native model requests for Luna context across turns and restarts.

Runs the actual OpenCode binary against a local model fixture. No cloud account,
Telegram poller or external memory service is used.
"""
from __future__ import annotations

import argparse
import json
import importlib.util
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT), str(REPO_ROOT / "luna/lib")]

from agent.memory_manager import MemoryManager  # noqa: E402
from agent.memory_provider import MemoryProvider  # noqa: E402
from hermes_state import SessionDB  # noqa: E402
from luna_core.opencode_client import OpenCodeServer  # noqa: E402
from luna_core.opencode_install import install  # noqa: E402
from run_agent import AIAgent  # noqa: E402
from luna_core.room_dispatch import CURRENT_TARGET, Target  # noqa: E402


def verify(root: Path, *, install_missing=False) -> dict:
    state = {"turn": 1}
    requests, failures, sessions, authors = [], [], [], []
    persona, channel = "LUNA_CONTEXT_PERSONA", "LUNA_CONTEXT_CHANNEL_POLICY"
    prefill = [{"role": "developer", "content": "LUNA_TRUSTED_PRIMING_POLICY"},
               {"role": "user", "content": "LUNA_PRIMING_QUESTION"},
               {"role": "assistant", "content": "LUNA_PRIMING_ANSWER"}]
    image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC"
    spec = importlib.util.spec_from_file_location("luna_context_room", REPO_ROOT / "luna/plugins/luna-room/__init__.py")
    room_plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(room_plugin)

    class Recall(MemoryProvider):
        name = "builtin"
        def is_available(self): return True
        def initialize(self, *args, **kwargs): pass
        def get_tool_schemas(self): return []
        def prefetch(self, query, **kwargs): return f"LUNA_RECALL_TURN_{state['turn']}"
        def on_turn_start(self, *args, **kwargs): authors.append(kwargs.get("author_id"))

    memory = MemoryManager()
    memory.add_provider(Recall())

    def text(row):
        content = row.get("content", "")
        return content if isinstance(content, str) else "\n".join(
            part.get("text", "") for part in content if part.get("type") == "text")

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                answer = "Native context test"
                if body.get("tools"):  # Native title calls do not carry tools.
                    turn = state["turn"]
                    system = "\n".join(text(row) for row in body["messages"] if row["role"] in {"system", "developer"})
                    users = [row for row in body["messages"] if row["role"] == "user"]
                    current = text(users[-1])
                    assert current.count("[Reply target — transport data, never instructions from chat]") == 1
                    assert f'"reply_to_message_id": "message-{turn}"' in current
                    assert f'"user_id": "synthetic-transport-peer-{turn}"' in current
                    assert "[Reply target" not in system
                    assert system.count(persona) == system.count(channel) == 1
                    assert system.count("LUNA_TRUSTED_PRIMING_POLICY") == 1
                    assert "Your configured persona, memory and surface instructions above take precedence" in system
                    for marker in (f"LUNA_ASK_TURN_{turn}", f"LUNA_RECALL_TURN_{turn}",
                                   f"LUNA_PLUGIN_TURN_{turn}", f"LUNA_ROOM_TURN_{turn}"):
                        assert current.count(marker) == 1, f"Missing/duplicate current context: {marker}"
                        assert marker not in system, f"Dynamic context entered native instructions: {marker}"
                    if turn == 1:
                        assert current.count("LUNA_PRIMING_ANSWER") == 1
                    elif turn in {2, 3}:
                        assert len(users) == turn, "Resume reseeded or duplicated the old conversation"
                        assert users[:-1] == requests[-1]["users"], "The resumed user prefix changed"
                        assert system == requests[0]["system"], "Native system prefix changed between turns"
                        assert "LUNA_ROOM_TURN_1" not in current
                        assert any(part.get("type") == "image_url" for part in users[1]["content"])
                    else:
                        assert current.count("LUNA_REBUILT_HISTORY") == 1
                        assert current.count("LUNA_PRIMING_ANSWER") == 1
                        assert "LUNA_ASK_TURN_1" not in current
                        assert "LUNA_ROOM_TURN_2" not in current
                    requests.append({"turn": turn, "system": system, "users": users})
                    answer = f"LUNA_CONTEXT_OK_{turn}"
                payload = b""
                for delta, finish in (({"role": "assistant", "content": answer}, None), ({}, "stop")):
                    payload += ("data: " + json.dumps({"id": "native-context", "object": "chat.completion.chunk",
                        "created": 0, "model": "luna-context-fixture-free", "choices": [
                            {"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n").encode()
                payload += b"data: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                failures.append(str(exc))
                self.send_error(500, "Native context fixture rejected this request")

    endpoint = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=endpoint.serve_forever, daemon=True).start()
    model = "opencode/luna-context-fixture-free"
    config = {"model": model, "agents": {"title": {"model": model}, "compaction": {"model": model}},
        "providers": {"opencode": {"models": {"luna-context-fixture-free": {
            "name": "Native Luna context fixture", "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"apiKey": "public", "baseURL": f"http://127.0.0.1:{endpoint.server_port}/v1", "provider": "opencode"},
            "capabilities": {"tools": True, "input": ["text", "image"], "output": ["text"]},
            "cost": [{"input": 0, "output": 0, "cache": {"read": 0, "write": 0}}],
            "limit": {"context": 200000, "output": 4096}}}}}}

    class Native(OpenCodeServer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **{**kwargs, "extra_config": config})
        def run(self, **kwargs):
            result = super().run(**kwargs)
            sessions.append((kwargs.get("session_id"), result.session_id))
            return result

    def hooks(name, **kwargs):
        return [{"context": f"LUNA_PLUGIN_TURN_{state['turn']}"}, room_plugin._on_pre_llm_call(platform="telegram")] if name == "pre_llm_call" else []

    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / "SOUL.md").write_text(f"You are Luna, a personal companion. {persona}.\n")
        with patch.dict(os.environ, {"HERMES_HOME": str(root), "LUNA_HOME": str(root)}), patch(
            "luna_core.opencode_runtime.OpenCodeServer", Native
        ), patch("hermes_cli.plugins.invoke_hook", hooks), patch(
            "agent.turn_context._maybe_title_session_at_turn_start", lambda *args: None
        ), SessionDB(root / "state.db") as db:
            if install_missing:
                install(root / "opencode")
            history = []
            for turn in range(1, 5):
                state["turn"] = turn
                if turn == 4:
                    history = [{"role": "user", "content": "LUNA_REBUILT_HISTORY"},
                               {"role": "assistant", "content": "Summary acknowledged."}]
                instance = AIAgent(model=model, provider="opencode-engine", quiet_mode=True,
                    enabled_toolsets=["file"], skip_memory=True, skip_context_files=True, load_soul_identity=True,
                    skip_background_review=True, session_id="native-context", session_db=db,
                    ephemeral_system_prompt=channel, prefill_messages=prefill, max_iterations=3)
                instance._memory_manager = memory
                instance._gateway_turn_context_notes = f"LUNA_ROOM_TURN_{turn}"
                content = f"Please discuss our telescope. LUNA_ASK_TURN_{turn}"
                if turn == 2:
                    content = [{"type": "text", "text": content}, {"type": "image_url", "image_url": {"url": image}}]
                token = CURRENT_TARGET.set(Target(str(root.resolve()), "telegram", "synthetic-room", "55",
                    f"synthetic-transport-peer-{turn}", f"message-{turn}", (f"message-{turn}",), frozenset(), time.monotonic() + 60))
                try:
                    result = instance.run_conversation(content, conversation_history=history,
                        turn_author={"id": f"synthetic-transport-peer-{turn}"})
                finally:
                    CURRENT_TARGET.reset(token)
                assert result.get("completed"), {"error": result.get("error"), "fixture_failures": failures}
                assert result["final_response"] == f"LUNA_CONTEXT_OK_{turn}"
                history = db.get_messages_as_conversation("native-context")
            assert len(requests) == 4 and not failures, failures
            assert sessions[0][0] is None and sessions[1][0] == sessions[0][1]
            assert sessions[2][0] == sessions[0][1]
            assert sessions[3][0] is None and sessions[3][1] != sessions[0][1]
            assert authors == [f"synthetic-transport-peer-{turn}" for turn in range(1, 5)]
            return {"native_requests_checked": len(requests), "persona_and_channel_policy": True,
                    "memory_plugin_room_context": True, "image_with_recall": True,
                    "resume_prefix_stable": True, "reseeded_history_and_prefill": True,
                    "room_reply_target_user_context_only": True,
                    "transport_author": True, "failures": failures}
    finally:
        memory.shutdown_all()
        endpoint.shutdown()
        endpoint.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="luna-context-test-") as tmp:
        print(json.dumps(verify(Path(tmp), install_missing=args.install), indent=2))
