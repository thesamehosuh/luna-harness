# SPDX-License-Identifier: Apache-2.0
# Attribution and inherited MIT notices: OPENCODE_NOTICES.txt
"""Authenticated loopback MCP bridge to the *running* Luna agent's tool dispatcher.

HTTP workers only enqueue calls. The owning conversation thread executes them,
retaining profile/identity/write-origin ContextVars and existing approval guards.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import queue
import re
import secrets
import threading
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable


@dataclass
class ToolRequest:
    name: str
    arguments: dict[str, Any]
    future: Future


class ToolBridge:
    name = "luna"

    def __init__(self, tools: list[dict]):
        self.token = secrets.token_hex(32)
        self.session_id: str | None = None
        self.closed = threading.Event()
        self.catalog_ready = threading.Event()
        self.pending: queue.Queue[ToolRequest] = queue.Queue(maxsize=32)
        self.names: dict[str, str] = {}
        self.tools = []
        for schema in tools:
            tool = schema.get("function", schema)
            original = tool["name"]
            wire = re.sub(r"[^a-zA-Z0-9_-]", "_", original)
            if wire != original or len(wire) > 48:
                wire = wire[:30] + "_" + hashlib.sha256(original.encode()).hexdigest()[:16]
            if wire in self.names:
                raise ValueError("Duplicate Luna MCP tool name")
            self.names[wire] = original
            self.tools.append({"name": wire, "description": tool.get("description", original),
                               "inputSchema": tool.get("parameters", {"type": "object", "properties": {}})})
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass  # Authorization and tool arguments never enter HTTP access logs.

            def respond(self, status, payload=None):
                body = json.dumps(payload).encode() if payload is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                self.wfile.write(body)

            def do_GET(self):
                self.respond(405)

            def do_POST(self):
                if self.path != "/mcp":
                    return self.respond(404)
                if self.headers.get("Origin") is not None or not hmac.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + bridge.token
                ):
                    return self.respond(403)
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 4 * 1024 * 1024:
                        return self.respond(413)
                    self.connection.settimeout(15)
                    request = json.loads(self.rfile.read(size))
                    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                        raise ValueError("Malformed MCP request")
                    if "id" not in request:
                        return self.respond(202)
                    result = bridge.handle(request)
                    self.respond(200, {"jsonrpc": "2.0", "id": request["id"], "result": result})
                    if request.get("method") == "tools/list":
                        bridge.catalog_ready.set()
                except (ValueError, TypeError, KeyError):
                    self.respond(400)
                except (OSError, TimeoutError):
                    self.close_connection = True

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True, name="luna-opencode-mcp")
        self.worker.start()

    @property
    def config(self) -> dict:
        return {"type": "remote", "url": f"http://127.0.0.1:{self.server.server_port}/mcp",
                "headers": {"Authorization": "Bearer " + self.token}, "oauth": False, "codemode": False,
                "timeout": {"execution": 1800000}}

    @property
    def actions(self) -> list[str]:
        return [f"{self.name}_{name}" for name in self.names]

    @staticmethod
    def denied() -> dict:
        return {"isError": True, "content": [{"type": "text", "text": "This Luna tool is unavailable in this session."}]}

    def handle(self, request: dict) -> dict:
        method = request["method"]
        if method == "initialize":
            version = request.get("params", {}).get("protocolVersion", "2025-03-26")
            return {"protocolVersion": version, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "luna", "version": "1.0.0"}}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.tools}
        if method != "tools/call":
            return {}
        params = request.get("params", {})
        session = params.get("_meta", {}).get("ai.opencode/sessionID")
        name = self.names.get(params.get("name"))
        arguments = params.get("arguments", {})
        if self.closed.is_set() or not self.session_id or session != self.session_id or not name or not isinstance(arguments, dict):
            return self.denied()
        call = ToolRequest(name, arguments, Future())
        try:
            self.pending.put_nowait(call)
        except queue.Full:
            return self.denied()
        while not self.closed.is_set():
            try:
                return call.future.result(timeout=0.25)
            except TimeoutError:
                continue
        return self.denied()

    def dispatch_pending(self, callback: Callable[[str, dict], dict]) -> None:
        """Called only on the owning agent thread, never by the HTTP handler."""
        try:
            call = self.pending.get_nowait()
        except queue.Empty:
            return
        if self.closed.is_set():
            call.future.set_result(self.denied())
            return
        try:
            call.future.set_result(callback(call.name, call.arguments))
        except BaseException:
            call.future.set_result(self.denied())
            raise

    def close(self) -> None:
        self.closed.set()
        self.session_id = None
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)
