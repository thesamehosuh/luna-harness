# SPDX-License-Identifier: Apache-2.0
# Attribution and inherited MIT notices: OPENCODE_NOTICES.txt
"""Small OpenCode 2 HTTP/SSE client using the same native API as Xratu.

OpenCode runs the inference/tool loop. Native filesystem, shell and subagent
requests are refused; only Luna's authenticated tool bridge is admitted.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import math
import os
import queue
import re
import secrets
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from luna_core.opencode_install import find_binary, isolated_environment, runtime_root


class OpenCodeAPIError(RuntimeError):
    def __init__(self, status: int, method: str, path: str):
        self.status_code = status
        super().__init__(f"OpenCode local API returned HTTP {status} for {method} {path.split('?')[0]}.")


class SessionUnavailable(RuntimeError):
    """A committed native binding is missing/moved; safe to seed a fresh session BEFORE prompting."""


def is_free_model(model: dict) -> bool:
    """Public free routes AND explicit zero prices in every advertised tier.

    Subscription allowances and absent pricing are deliberately excluded.
    """
    if not isinstance(model, dict) or not isinstance(model.get("id"), str):
        return False
    provider, name = model.get("providerID"), model["id"]
    public = provider == "opencode" and (name == "big-pickle" or name.endswith("-free"))
    costs = model.get("cost")
    if not public or not isinstance(costs, list) or not costs:
        return False
    for cost in costs:
        if not isinstance(cost, dict) or not isinstance(cost.get("cache"), dict):
            return False
        values = (cost.get("input"), cost.get("output"), cost["cache"].get("read"), cost["cache"].get("write"))
        if not all(type(value) in (int, float) and value == 0 for value in values):
            return False
    return bool(model.get("enabled") and model.get("status") != "deprecated"
                and model.get("capabilities", {}).get("tools")
                and "text" in model.get("capabilities", {}).get("output", []))


def public_model(model: dict) -> dict:
    """Catalog projection safe for the dashboard; never expose native settings/auth."""
    return {"id": f"{model['providerID']}/{model['id']}", "name": model.get("name", model["id"]),
            "free": is_free_model(model), "context": model.get("limit", {}).get("context"),
            "vision": "image" in model.get("capabilities", {}).get("input", [])}


@dataclass
class NativeResult:
    session_id: str
    text: str = ""
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost: float = 0
    compacted: bool = False
    texts: dict[str, str] = field(default_factory=dict)


class OpenCodeServer:
    def __init__(self, root: Path | None = None, workspace_key: str = "setup", ephemeral: bool = False,
                 bridge=None, extra_config: dict | None = None):
        self.install_root = root or runtime_root()
        self.workspace_id = hashlib.sha256(workspace_key.encode()).hexdigest()[:32]
        self.root = self.install_root / "sessions" / self.workspace_id
        self.workspace = self.root / "home" / "workspace"
        self._leases = ()
        self.process = None
        self.stream = None
        self.reader = None
        self.headers = {}
        self.base_url = ""
        self.ephemeral = ephemeral
        self.active_session_id = None
        self.bridge = bridge
        self.extra_config = extra_config or {}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def __enter__(self):
        try:
            return self._start()
        except BaseException:
            self.close()
            raise

    def _start(self):
        found = find_binary(self.install_root)
        if found is None:
            raise RuntimeError("Install OpenCode from Luna's Setup page first.")
        from luna_core.native_resources import lease
        self._leases = lease(self.install_root, self.workspace_id)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.root / ".last_used").touch()
        if not (self.root / ".created").exists():
            (self.root / ".created").touch()
        binary, self.version = found
        env = isolated_environment(self.root)
        # Configure the bridge before the native project starts. Hot-adding it can
        # race the first inference request's tool snapshot on a cold native location.
        config = {**self.extra_config, "update": "disable", "share": "disabled"}
        if self.bridge:
            config["mcp"] = {"servers": {self.bridge.name: self.bridge.config}}
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        password = secrets.token_hex(32)
        env["OPENCODE_PASSWORD"] = password
        self.headers = {"Authorization": "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()}
        self.process = subprocess.Popen([str(binary), "serve", "--hostname=127.0.0.1", "--port=0"],
            cwd=self.workspace, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, start_new_session=os.name != "nt")
        lines = queue.Queue(maxsize=256)

        def drain():
            for line in self.process.stdout:
                try:
                    lines.put_nowait(line[-8192:])
                except queue.Full:
                    pass
            with contextlib.suppress(queue.Full):
                lines.put_nowait(None)

        self.log_reader = threading.Thread(target=drain, daemon=True, name="luna-opencode-log")
        self.log_reader.start()
        deadline = time.monotonic() + 45
        try:
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=min(1, max(0.01, deadline - time.monotonic())))
                except queue.Empty:
                    continue
                if line is None:
                    raise RuntimeError("OpenCode exited before its local server became ready.")
                if match := re.search(r"server listening on (http://127\.0\.0\.1:\d+)", line):
                    self.base_url = match.group(1)
                    self.request("GET", "/api/info")
                    return self
            raise TimeoutError("OpenCode startup timed out.")
        except BaseException:
            self.close()
            raise

    def request(self, method: str, path: str, body=None, *, location=False, timeout=30):
        if location:
            path += ("&" if "?" in path else "?") + urllib.parse.urlencode({"location[directory]": str(self.workspace)})
        headers = {**self.headers, "Content-Type": "application/json"}
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
                if len(raw) > 16 * 1024 * 1024:
                    raise RuntimeError("OpenCode response exceeds size limit.")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise OpenCodeAPIError(exc.code, method, path) from None

    def models(self) -> list[dict]:
        for attempt in range(5):
            response = self.request("GET", "/api/model", location=True)
            models = response.get("data", [])
            if models:
                return models
            time.sleep(0.2 * (attempt + 1))
        return []

    def _events(self, output: queue.Queue, stream):
        try:
            data_lines, size = [], 0
            while line := stream.readline(4 * 1024 * 1024 + 1):
                size += len(line)
                if size > 4 * 1024 * 1024:
                    raise RuntimeError("OpenCode event exceeds size limit.")
                if line.strip() == b"":
                    if data_lines:
                        event = json.loads(b"\n".join(data_lines))
                        if isinstance(event, dict):
                            output.put(event, timeout=2)
                    data_lines, size = [], 0
                elif line.startswith(b"data:"):
                    data_lines.append(line[5:].strip())
            raise RuntimeError("OpenCode event stream closed before the turn finished.")
        except Exception as exc:
            try:
                output.put(exc, timeout=1)
            except queue.Full:
                pass

    def run(self, *, model: str, prompt: str, instructions: str, session_id: str | None = None,
            bridge=None, dispatch: Callable | None = None, interrupted: Callable = lambda: False,
            timeout: float = 180, max_steps: int = 90, on_step: Callable | None = None,
            files: list[dict] | None = None, free_only: bool = True) -> NativeResult:
        if interrupted():
            raise InterruptedError("OpenCode turn stopped.")
        selected = next((item for item in self.models() if f"{item.get('providerID')}/{item.get('id')}" == model), None)
        if selected is None or (free_only and not is_free_model(selected)):
            raise RuntimeError("The selected model is unavailable or no longer advertises zero prices. Choose a free model in Setup.")
        if not selected.get("enabled") or selected.get("status") == "deprecated":
            raise RuntimeError("The selected native model is unavailable.")
        if files and "image" not in selected.get("capabilities", {}).get("input", []):
            raise ValueError("This free model cannot read images. Choose a model with image support in Setup.")
        permissions = [{"action": "*", "resource": "*", "effect": "ask"},
                       {"action": "subagent", "resource": "*", "effect": "deny"}]
        if bridge:
            permissions.extend({"action": action, "resource": "*", "effect": "allow"} for action in bridge.actions)
            if bridge is not self.bridge:
                self.request("PUT", "/api/experimental/mcp/luna", {"config": bridge.config}, location=True)
            # Adding a native MCP server is asynchronous. Its catalog must be ready on
            # the first request, or tool availability (and the cached prefix) drifts.
            ready_by = time.monotonic() + 15
            while True:
                statuses = self.request("GET", "/api/mcp", location=True).get("data", [])
                status = next((item.get("status", {}).get("status") for item in statuses if item.get("name") == "luna"), None)
                if status == "connected" and bridge.catalog_ready.is_set():
                    break
                if interrupted():
                    raise InterruptedError("OpenCode turn stopped.")
                if status not in {"pending", "connecting", "connected", None} or time.monotonic() >= ready_by:
                    raise RuntimeError("OpenCode could not connect to Luna's tool bridge.")
                time.sleep(0.1)
        if session_id:
            # A missing/mismatched session is an error. Never silently replay a potentially executed turn.
            try:
                existing = self.request("GET", f"/api/session/{urllib.parse.quote(session_id, safe='')}")["data"]
            except OpenCodeAPIError as exc:
                if exc.status_code == 404:
                    raise SessionUnavailable("OpenCode's committed session no longer exists.") from None
                raise
            if existing.get("location", {}).get("directory") != str(self.workspace):
                raise SessionUnavailable("OpenCode session belongs to a different Luna workspace.")
            self.request("PATCH", f"/api/session/{session_id}", {"permissions": permissions})
        else:
            provider, name = model.split("/", 1)
            created = self.request("POST", "/api/session", {"agent": "build", "model": {"providerID": provider, "id": name},
                "location": {"directory": str(self.workspace)}, "permissions": permissions})["data"]
            session_id = created["id"]
            self.request("PUT", f"/api/experimental/session/{session_id}/instructions/entries/luna.policy", {"value": instructions})
        if bridge:
            bridge.session_id = session_id
        self.active_session_id = session_id
        result = NativeResult(session_id)
        self.stream = self.opener.open(urllib.request.Request(self.base_url + "/api/event",
            headers={**self.headers, "Accept": "text/event-stream"}), timeout=45)
        events = queue.Queue(maxsize=2048)
        self.reader = threading.Thread(target=self._events, args=(events, self.stream), daemon=True, name="luna-opencode-events")
        self.reader.start()
        started, retries = False, 0
        deadline = time.monotonic() + timeout
        try:
            if interrupted():
                raise InterruptedError("OpenCode turn stopped.")
            self.request("POST", f"/api/session/{session_id}/prompt", {"text": prompt, **({"files": files} if files else {})})
            while time.monotonic() < deadline:
                if interrupted():
                    raise InterruptedError("OpenCode turn stopped.")
                if bridge and dispatch:
                    bridge.dispatch_pending(dispatch)
                try:
                    event = events.get(timeout=0.1)
                except queue.Empty:
                    if self.process.poll() is not None:
                        raise RuntimeError("OpenCode exited during the turn.")
                    continue
                if isinstance(event, Exception):
                    raise event
                data, kind = event.get("data", {}), event.get("type")
                if kind == "form.created":
                    data = data.get("form", {})
                if data.get("sessionID") != session_id:
                    continue
                if kind == "session.execution.started":
                    started = True
                elif kind == "permission.asked":
                    # Native tools must never bypass Luna's own dispatcher, even in /yolo mode.
                    self.request("POST", f"/api/session/{session_id}/permission/{urllib.parse.quote(data['id'], safe='')}/reply",
                                 {"decision": "reject", "message": "Use Luna MCP tools for this task. Native tools are unavailable."})
                elif kind == "form.created":
                    self.request("DELETE", f"/api/session/{session_id}/form/{urllib.parse.quote(data['id'], safe='')}")
                elif kind == "session.text.delta":
                    key = data.get("assistantMessageID", "final")
                    result.texts[key] = result.texts.get(key, "") + data.get("delta", "")
                elif kind == "session.compaction.ended":
                    result.compacted = True
                elif kind == "session.retry.scheduled":
                    retries += 1
                    if retries > 2:
                        raise RuntimeError("The OpenCode model is unavailable after retries. Test it or select another model in Setup.")
                elif kind == "session.step.started":
                    result.steps += 1
                    if result.steps > max_steps or (on_step and not on_step()):
                        raise RuntimeError("OpenCode reached Luna's turn iteration limit.")
                elif kind == "session.step.ended":
                    tokens = data.get("tokens", {})
                    cache = tokens.get("cache", {})
                    result.input_tokens += self._number(tokens.get("input")) + self._number(cache.get("read")) + self._number(cache.get("write"))
                    result.output_tokens += self._number(tokens.get("output")) + self._number(tokens.get("reasoning"))
                    result.cached_tokens += self._number(cache.get("read"))
                    result.cost += self._number(data.get("cost"))
                elif started and kind == "session.execution.succeeded":
                    result.text = next(reversed(result.texts.values()), "")
                    return result
                elif started and kind in {"session.execution.failed", "session.execution.interrupted"}:
                    error = data.get("error", {})
                    message = error.get("message") if isinstance(error, dict) else str(error)
                    raise RuntimeError("OpenCode could not finish the turn" + (f": {message[:800]}" if message else "."))
            raise TimeoutError("OpenCode exceeded Luna's configured turn timeout.")
        finally:
            if bridge:
                bridge.session_id = None
            self._close_events()
            # The managed process is always stopped by the surrounding context, including on cancel.

    @staticmethod
    def _number(value):
        return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else 0

    def _close_events(self):
        stream, self.stream = self.stream, None
        if stream:
            # Wake a reader blocked in readline before closing its buffered file. Closing
            # the buffer alone from another thread can wait for the next heartbeat.
            with contextlib.suppress(AttributeError, OSError):
                stream.fp.raw._sock.shutdown(socket.SHUT_RDWR)
            stream.close()
        if self.reader:
            self.reader.join(timeout=2)
            self.reader = None

    def close(self):
        process = self.process
        if process and process.poll() is None:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                import psutil
                for child in psutil.Process(process.pid).children(recursive=True):
                    child.kill()
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.wait(timeout=3)
        self._close_events()
        if getattr(self, "log_reader", None):
            self.log_reader.join(timeout=2)
        if process and process.stdout:
            process.stdout.close()
        if self._leases:
            (self.root / ".last_used").touch()
            for handle in self._leases:
                handle.close()
            self._leases = ()

    def __exit__(self, *_args):
        if self.ephemeral and self.active_session_id:
            try:
                self.request("DELETE", f"/api/session/{self.active_session_id}", timeout=5)
            except Exception:
                pass
        self.close()
        if self.ephemeral:
            shutil.rmtree(self.root, ignore_errors=True)
