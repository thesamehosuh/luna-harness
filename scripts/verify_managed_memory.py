#!/usr/bin/env python3
"""Exercise guided memory with real offline embeddings and Honcho, using synthetic reasoning only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import ExitStack
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "luna/lib")]
REQUESTS = 0


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        global REQUESTS
        REQUESTS += 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        schema = (body.get("response_format") or {}).get("json_schema", {}).get("schema", {})
        markers = re.findall(r"luna-check-[0-9a-f]{16}", json.dumps(body))
        marker = markers[-1] if markers else "synthetic-memory"
        prompt = "\n".join(str(row.get("content", "")) for row in body.get("messages", []))
        preflight = "ok" in schema.get("properties", {}) or 'Returnexactly{"ok":true}' in prompt.replace(" ", "")
        result = {"ok": True} if preflight else {"explicit": [{"content": "The synthetic user likes " + marker + "."}]}
        if body.get("stream"):
            content = json.dumps(result)
            def frame(delta, finish=None):
                return "data: " + json.dumps({"id": "synthetic-native", "object": "chat.completion.chunk", "created": 0,
                    "model": body.get("model"), "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"
            payload = (frame({"role": "assistant", "content": content}) + frame({}, "stop") + "data: [DONE]\n\n").encode()
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers(); self.wfile.write(payload)
            return
        payload = json.dumps({"id": "synthetic-reasoning", "object": "chat.completion", "created": 0,
            "model": body.get("model"), "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(result)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 32, "completion_tokens": 16, "total_tokens": 48}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embeddings", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("/tmp/luna-managed-memory-integration.json"))
    parser.add_argument("--native-fixture", action="store_true", help="exercise real OpenCode HTTP/SSE inference against the local zero-cost reasoning fixture")
    args = parser.parse_args()
    import yaml
    from luna_core import managed_memory, memory_worker, data_ops
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("LUNA_", "HERMES_", "OPENAI_", "HONCHO_")) and not k.endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))}
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    result = {}
    with tempfile.TemporaryDirectory(prefix="luna-managed-memory-") as temporary, patch.dict(os.environ, clean, clear=True), ExitStack() as fixtures:
        home = Path(temporary)
        os.environ.update(HERMES_HOME=str(home), LUNA_HOME=str(home), OPENAI_API_KEY="synthetic-local-fixture",
                          LUNA_EMBEDDING_BUNDLE=str(args.embeddings.resolve()), PYTHONPATH=os.pathsep.join((str(ROOT), str(ROOT / "luna/lib"))))
        config = yaml.safe_load((ROOT / "luna/config/config.yaml.luna").read_text())
        config["model"] = {"provider": "custom", "default": "synthetic-local-reasoning", "base_url": f"http://127.0.0.1:{server.server_port}/v1", "key_env": "OPENAI_API_KEY"}
        if args.native_fixture:
            config["model"] = {"provider": "opencode-engine", "default": "opencode/luna-memory-fixture-free"}
        config["honcho"].update(baseUrl="http://127.0.0.1:9", workspace="luna-synthetic-fixture")
        (home / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
        (home / "SOUL.md").write_text("# Synthetic fixture only\n")
        shutil.copytree(ROOT / "luna/honcho", home / "honcho")
        if args.native_fixture:
            import socket
            import secrets
            import uvicorn
            from luna_core import opencode_aux
            from luna_core.opencode_client import OpenCodeServer
            from luna_core.opencode_install import find_binary, install
            from luna_cli.memory_bridge import create_app
            if find_binary() is None: install()
            model = config["model"]["default"]
            native_config = {"model": model, "agents": {"title": {"model": model}, "compaction": {"model": model}},
                "providers": {"opencode": {"models": {"luna-memory-fixture-free": {
                    "name": "Synthetic memory fixture", "package": "@opencode/ai/providers/openai-compatible",
                    "settings": {"apiKey": "synthetic", "baseURL": f"http://127.0.0.1:{server.server_port}/v1", "provider": "opencode"},
                    "enabled": True, "status": "active", "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
                    "cost": [{"input": 0, "output": 0, "cache": {"read": 0, "write": 0}}], "limit": {"context": 200000, "output": 4096}}}}}}
            class NativeFixtureServer(OpenCodeServer):
                def __init__(self, *a, **kw): super().__init__(*a, **{**kw, "extra_config": native_config})
                def run(self, **kwargs):
                    assert kwargs["model"] == model
                    return super().run(**kwargs)
            fixtures.enter_context(patch.object(opencode_aux, "OpenCodeServer", NativeFixtureServer))
            sock = socket.socket(); sock.bind(("0.0.0.0", 0))
            key = secrets.token_urlsafe(48)
            worker = {"nonce": "synthetic-native", "home": str(home), "port": sock.getsockname()[1], "key": key}
            app = create_app(key, worker, home / "honcho/.fixture-ready.json")
            bridge = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
            bridge_thread = threading.Thread(target=lambda: bridge.run(sockets=[sock]), daemon=True); bridge_thread.start()
            import time
            deadline = time.monotonic() + 10
            while not bridge.started and time.monotonic() < deadline: time.sleep(0.05)
            def stop_fixture(): bridge.should_exit = True; bridge_thread.join(timeout=10)
            fixtures.callback(stop_fixture)
            fixtures.enter_context(patch.object(memory_worker, "ensure", return_value=worker))
            fixtures.enter_context(patch.object(memory_worker, "stop", side_effect=stop_fixture))
        try:
            print("Running the real managed-memory setup in a disposable home", flush=True)
            result = managed_memory.setup(180)
            result["reasoning_requests"] = REQUESTS
            result["progress"] = managed_memory.status()
            if not result["ok"]:
                command = data_ops.compose_command(home / "honcho", "logs", "--no-color", "--tail", "100", "api", "deriver", "bootstrap")
                logs = subprocess.run(command, capture_output=True, text=True, timeout=30).stdout
                from luna_core.env import parse_env_file
                for key, value in parse_env_file(home / "honcho/.env").items():
                    if "PASSWORD" in key or key.endswith("API_KEY"): logs = logs.replace(value, "[redacted]")
                diagnostics = args.output.with_suffix(".diagnostics.log")
                diagnostics.write_text(logs); diagnostics.chmod(0o600)
        finally:
            try: memory_worker.stop()
            except Exception: pass
            if (home / "honcho/.env").exists():
                subprocess.run(data_ops.compose_command(home / "honcho", "down", "--volumes", "--remove-orphans"), capture_output=True, timeout=90)
    server.shutdown(); server.server_close()
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__": raise SystemExit(main())
