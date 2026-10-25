"""Exercise the real OpenCode binary, Luna MCP tools and finalizer in a scratch home.

Default: a local deterministic model endpoint, with no model-service credentials.
Optional: --model provider/model --use-native-login tests an existing OpenCode
account. The model is supplied by the operator; nothing is changed in Luna config.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT), str(REPO_ROOT / "luna/lib")]

from luna_core.opencode_client import OpenCodeServer  # noqa: E402
from luna_core.opencode_install import find_binary, install, isolated_environment  # noqa: E402
from run_agent import AIAgent  # noqa: E402


def verify(root: Path, *, model: str | None = None, use_native_login=False, install_missing=False) -> dict:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    native_data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    fixture, marker = root / "synthetic.txt", "LUNA_NATIVE_" + uuid.uuid4().hex[:12]
    fixture.write_text(marker + "\n")
    calls, failures = [], []
    endpoint = None

    class ModelHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(body)
                tools = [tool["function"]["name"] for tool in body.get("tools", [])]
                system = "\n".join(str(row.get("content", "")) for row in body["messages"]
                                   if row.get("role") in {"system", "developer"})
                # Native title generation may inherit the conversation's policy. Recognize
                # its explicit system instruction before classifying main inference;
                # an empty main catalog must still fail the tool assertion below.
                title_request = any(str(row.get("content", "")).startswith(
                    "You name conversations so the user can find them later in a list of past sessions."
                ) for row in body["messages"] if row.get("role") == "system")
                if title_request or "Use only the Luna MCP tools supplied for this conversation." not in system:
                    delta, finish = {"role": "assistant", "content": "Native Luna tool test"}, "stop"
                elif not any(row.get("role") == "tool" and marker in json.dumps(row) for row in body["messages"]):
                    if "luna_read_file" not in tools:
                        raise AssertionError("Luna's tools were missing from the first native inference catalog")
                    delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "native_read",
                        "type": "function", "function": {"name": "luna_read_file",
                        "arguments": json.dumps({"path": str(fixture)})}}]}
                    finish = "tool_calls"
                else:
                    delta, finish = {"role": "assistant", "content": marker}, "stop"

                def frame(delta, finish=None):
                    return ("data: " + json.dumps({"id": "luna-native-test", "object": "chat.completion.chunk",
                        "created": 0, "model": "luna-native-fixture-free", "choices": [{"index": 0,
                        "delta": delta, "finish_reason": finish}]}) + "\n\n").encode()

                payload = frame(delta) + frame({}, finish) + b"data: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                failures.append(str(exc))
                self.send_error(500, "Native test fixture rejected the request")

    if model is None:
        model = "opencode/luna-native-fixture-free"
        endpoint = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
        threading.Thread(target=endpoint.serve_forever, daemon=True).start()
        config = {"providers": {"opencode": {"models": {"luna-native-fixture-free": {
            "name": "Luna native test fixture", "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"apiKey": "public", "baseURL": f"http://127.0.0.1:{endpoint.server_port}/v1", "provider": "opencode"},
            "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
            "cost": [{"input": 0, "output": 0, "cache": {"read": 0, "write": 0}}],
            "limit": {"context": 200000, "output": 4096},
        }}}}}
    else:
        config = {}
    config.update(model=model, agents={"title": {"model": model}, "compaction": {"model": model}})

    def environment(path):
        env = isolated_environment(path)
        if use_native_login:
            # Explicit developer opt-in. The native process reads its own credential
            # store; credentials are never copied into Luna or returned to this script.
            env["XDG_DATA_HOME"] = native_data
        return env

    class NativeTestServer(OpenCodeServer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **{**kwargs, "extra_config": config, "ephemeral": True})

        def run(self, **kwargs):
            if kwargs.get("model") != model:
                raise AssertionError("Native test unexpectedly changed models")
            return super().run(**{**kwargs, "free_only": not use_native_login})

    try:
        with patch.dict(os.environ, {"HERMES_HOME": str(root), "LUNA_HOME": str(root)}):
            if install_missing:
                install(root / "opencode")
            if find_binary(root / "opencode") is None:
                raise RuntimeError("No compatible OpenCode binary. Re-run this developer check with --install.")
            with patch("luna_core.opencode_client.isolated_environment", environment), patch(
                "luna_core.opencode_runtime.OpenCodeServer", NativeTestServer
            ), patch(
                "agent.turn_context._maybe_title_session_at_turn_start", lambda *args: None
            ):
                agent = AIAgent(model=model, provider="opencode-engine", quiet_mode=True,
                    enabled_toolsets=["file"], skip_memory=True, skip_context_files=True,
                    skip_background_review=True, max_iterations=4)
                result = agent.run_conversation(f"Use Luna's read_file tool to read only {fixture}. "
                    "Reply with the exact marker in that file and nothing else. Do not modify files or use other tools.")
                tools = [call["function"]["name"] for row in result["messages"] for call in row.get("tool_calls", [])]
                report = {"model": model, "completed": result.get("completed"), "tool_calls": tools,
                    "marker_matches": result.get("final_response", "").strip() == marker,
                    "fixture_unchanged": fixture.read_text() == marker + "\n",
                    "local_inference_requests": len(calls), "failures": failures,
                    "error": result.get("error")}
                if not (report["completed"] and report["marker_matches"] and report["fixture_unchanged"]
                        and tools == ["read_file"] and not failures):
                    raise RuntimeError(json.dumps(report))
                return report
    finally:
        if endpoint:
            endpoint.shutdown()
            endpoint.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="install the verified runtime if needed")
    parser.add_argument("--model", help="optional live native provider/model; default uses a local fixture")
    parser.add_argument("--use-native-login", action="store_true", help="explicitly use existing OpenCode account storage")
    args = parser.parse_args()
    if args.use_native_login and not args.model:
        parser.error("--use-native-login requires an explicitly selected --model")
    with tempfile.TemporaryDirectory(prefix="luna-native-test-") as tmp:
        print(json.dumps(verify(Path(tmp), model=args.model, use_native_login=args.use_native_login,
                                install_missing=args.install), indent=2))
