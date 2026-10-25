"""Native engine policy, catalog, protocol and bridge tests; no external network."""
from __future__ import annotations

import copy
import io
import json
import os
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from luna_core.opencode_bridge import ToolBridge
from luna_core.opencode_client import OpenCodeServer, is_free_model, public_model
from luna_core.opencode_install import check_binary, isolated_environment

FREE = {"id": "test-free", "providerID": "opencode", "enabled": True, "status": "active",
        "cost": [{"input": 0, "output": 0, "cache": {"read": 0, "write": 0}}],
        "capabilities": {"tools": True, "input": ["text", "image"], "output": ["text"]},
        "limit": {"context": 200000}, "settings": {"apiKey": "synthetic-private-value"}}


@pytest.mark.parametrize("changes", [
    {"cost": []}, {"cost": None}, {"providerID": "opencode-go"}, {"providerID": "some-subscription"},
    {"id": "paid-model"}, {"id": None}, {"enabled": False}, {"status": "deprecated"},
    {"cost": [{"input": 0, "output": 0, "cache": {"read": 0}}]},
    {"cost": [{"input": False, "output": 0, "cache": {"read": 0, "write": 0}}]},
    {"cost": FREE["cost"] + [{"input": 1, "output": 0, "cache": {"read": 0, "write": 0}}]},
    {"capabilities": {"tools": False, "output": ["text"]}},
])
def test_free_requires_public_route_and_every_explicit_zero_price(changes):
    assert not is_free_model({**FREE, **changes})


def test_catalog_strips_native_secrets():
    assert is_free_model(FREE)
    assert public_model(FREE) == {"id": "opencode/test-free", "name": "test-free", "free": True,
                                  "context": 200000, "vision": True}
    assert "synthetic-private" not in json.dumps(public_model(FREE))


def test_native_environment_isolates_auth_and_keeps_loopback_direct(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-token")
    monkeypatch.setenv("OPENCODE_API_KEY", "synthetic-native-key")
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"mcp":{"untrusted":{}}}')
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("NO_PROXY", "unrelated.invalid")
    env = isolated_environment(tmp_path)
    assert not any(key in env for key in ("OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "OPENCODE_API_KEY", "OPENCODE_CONFIG_CONTENT"))
    assert env["HOME"] == str(tmp_path / "home")
    assert env["HTTPS_PROXY"] == "http://proxy.invalid:8080"
    assert env["NO_PROXY"] == env["no_proxy"] == "127.0.0.1,localhost,::1"
    assert all(Path(env[key]).is_relative_to(tmp_path) for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"))


@pytest.mark.parametrize("reported,valid", [("opencode v2.1.2\n", True), ("2.0.30", True), ("1.9.9", False), ("2.0.29", False), ("3.0.0", False), ("2.2.0", False)])
def test_binary_version_contract(tmp_path, monkeypatch, reported, valid):
    monkeypatch.setattr("luna_core.opencode_install.subprocess.run", lambda *a, **k: SimpleNamespace(stdout=reported, stderr=""))
    if valid:
        assert check_binary(Path("opencode"), tmp_path) in reported
    else:
        with pytest.raises(RuntimeError):
            check_binary(Path("opencode"), tmp_path)


def test_mcp_auth_origin_session_and_owner_thread():
    bridge = ToolBridge([{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}])
    try:
        url = bridge.config["url"]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        for headers in ({}, {**bridge.config["headers"], "Origin": "http://untrusted.invalid"}):
            with pytest.raises(urllib.error.HTTPError) as denied:
                opener.open(urllib.request.Request(url, data=body, headers=headers), timeout=5)
            assert denied.value.code == 403
        with opener.open(urllib.request.Request(url, data=body, headers=bridge.config["headers"]), timeout=5) as response:
            assert json.load(response)["result"]["tools"][0]["name"] == "read_file"
        bridge.session_id = "root-session"
        def request(session):
            return {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "synthetic"}, "_meta": {"ai.opencode/sessionID": session}}}
        assert bridge.handle(request("other-session"))["isError"]
        owner = threading.get_ident()
        called = []
        def dispatch(name, args):
            called.append((threading.get_ident(), name, args))
            return {"content": [{"type": "text", "text": "safe result"}]}
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(bridge.handle, request("root-session"))
            for _ in range(100):
                bridge.dispatch_pending(dispatch)
                if result.done():
                    break
                threading.Event().wait(0.01)
            assert result.result(timeout=2)["content"][0]["text"] == "safe result"
        assert called == [(owner, "read_file", {"path": "synthetic"})]
    finally:
        bridge.close()


def test_closing_bridge_settles_pending_tools():
    bridge = ToolBridge([{"name": "read_file"}])
    bridge.session_id = "session"
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(bridge.handle, {"method": "tools/call", "params": {"name": "read_file", "_meta": {"ai.opencode/sessionID": "session"}}})
        bridge.close()
        assert result.result(timeout=2)["isError"]


def protocol_server(tmp_path, monkeypatch, events, models=None):
    server = OpenCodeServer(tmp_path)
    calls = []
    server.models = lambda: models if models is not None else [copy.deepcopy(FREE)]
    def request(method, path, body=None, **kwargs):
        calls.append((method, path, body))
        if method == "POST" and path == "/api/session":
            return {"data": {"id": "session"}}
        if method == "GET" and path == "/api/session/session":
            return {"data": {"location": {"directory": str(server.workspace)}}}
    server.request = request
    frames = b"".join(b"data: " + json.dumps({"type": kind, "data": {"sessionID": "session", **data}}).encode() + b"\r\n\r\n" for kind, data in events)
    server.opener = SimpleNamespace(open=lambda *a, **kw: io.BytesIO(frames))
    server.base_url = "http://127.0.0.1:1"
    server.process = SimpleNamespace(poll=lambda: None)
    return server, calls


def test_native_protocol_refuses_native_tools_filters_events_and_returns_final_step(tmp_path, monkeypatch):
    server, calls = protocol_server(tmp_path, monkeypatch, [
        ("session.execution.succeeded", {}),  # stale success before our execution
        ("session.execution.started", {}),
        ("session.step.started", {}),
        ("session.text.delta", {"assistantMessageID": "interim", "delta": "I will check."}),
        ("permission.asked", {"id": "permission", "action": "shell"}),
        ("form.created", {"sessionID": None, "form": {"sessionID": "session", "id": "native-form"}}),
        ("session.text.delta", {"sessionID": "other", "delta": "private other session"}),
        ("session.step.ended", {"tokens": {"input": 10, "output": 2, "reasoning": 3, "cache": {"read": 5, "write": 0}}, "cost": 0}),
        ("session.step.started", {}),
        ("session.text.delta", {"assistantMessageID": "final", "delta": "The answer."}),
        ("session.execution.succeeded", {}),
    ])
    result = server.run(model="opencode/test-free", prompt="test", instructions="stable policy")
    assert result.text == "The answer."
    assert result.steps == 2 and result.input_tokens == 15 and result.output_tokens == 5
    reply = next(body for method, path, body in calls if path.endswith("/permission/permission/reply"))
    assert reply["decision"] == "reject"
    assert any(method == "DELETE" and path.endswith("/form/native-form") for method, path, _ in calls)
    assert sum("instructions/entries" in path for _, path, _ in calls) == 1


def test_resume_does_not_rewrite_instructions(tmp_path, monkeypatch):
    server, calls = protocol_server(tmp_path, monkeypatch, [
        ("session.execution.started", {}), ("session.text.delta", {"delta": "OK"}), ("session.execution.succeeded", {}),
    ])
    server.run(model="opencode/test-free", prompt="new user and dynamic recall", instructions="stable policy", session_id="session")
    assert not any("instructions/entries" in path for _, path, _ in calls)


def test_price_change_blocks_before_any_session_or_prompt(tmp_path, monkeypatch):
    paid = copy.deepcopy(FREE)
    paid["cost"][0]["output"] = 1
    server, calls = protocol_server(tmp_path, monkeypatch, [], [paid])
    with pytest.raises(RuntimeError, match="no longer advertises zero"):
        server.run(model="opencode/test-free", prompt="test", instructions="policy")
    assert calls == []


@pytest.mark.parametrize("event,error", [("session.execution.failed", "usage limit"), ("session.execution.interrupted", "could not finish")])
def test_native_errors_propagate_without_paid_fallback(tmp_path, monkeypatch, event, error):
    server, calls = protocol_server(tmp_path, monkeypatch, [("session.execution.started", {}), (event, {"error": {"message": "usage limit"}})])
    with pytest.raises(RuntimeError, match=error):
        server.run(model="opencode/test-free", prompt="test", instructions="policy")
    assert sum(path == "/api/session/session/prompt" for _, path, _ in calls) == 1


def test_cancel_and_budget_stop_native_execution(tmp_path, monkeypatch):
    server, _ = protocol_server(tmp_path, monkeypatch, [])
    with pytest.raises(InterruptedError):
        server.run(model="opencode/test-free", prompt="test", instructions="policy", interrupted=lambda: True)
    server, _ = protocol_server(tmp_path, monkeypatch, [("session.execution.started", {}), ("session.step.started", {})])
    with pytest.raises(RuntimeError, match="iteration limit"):
        server.run(model="opencode/test-free", prompt="test", instructions="policy", on_step=lambda: False)


def test_each_native_turn_closes_its_own_event_reader_before_the_next(tmp_path, monkeypatch):
    server, _ = protocol_server(tmp_path, monkeypatch, [])
    class BlockingStream:
        def __init__(self, text):
            self.lines = iter([b"data: " + json.dumps({"type": kind, "data": {"sessionID": "session", **data}}).encode() + b"\n\n" for kind, data in [
                ("session.execution.started", {}), ("session.text.delta", {"delta": text}), ("session.execution.succeeded", {}),
            ]])
            self.buffer = b""
            self.closed = threading.Event()
        def readline(self, *_args):
            if not self.buffer:
                self.buffer = next(self.lines, b"")
            if self.buffer:
                line, _, self.buffer = self.buffer.partition(b"\n")
                return line + b"\n"
            self.closed.wait(timeout=5)
            return b""
        def close(self):
            self.closed.set()
    first, second = BlockingStream("first"), BlockingStream("second")
    streams = iter([first, second])
    server.opener = SimpleNamespace(open=lambda *a, **kw: next(streams))
    try:
        assert server.run(model="opencode/test-free", prompt="one", instructions="policy").text == "first"
        assert first.closed.is_set() and server.reader is None
        assert server.run(model="opencode/test-free", prompt="two", instructions="policy").text == "second"
        assert second.closed.is_set() and server.reader is None
    finally:
        first.close()
        second.close()


def test_image_snapshot_and_no_arbitrary_file_uri(tmp_path, monkeypatch):
    from luna_core.opencode_attachments import prompt_parts
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    text, files = prompt_parts([{"type": "text", "text": "look at this"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,c3ludGhldGlj"}}])
    assert text == "look at this"
    path = Path(urllib.request.url2pathname(urllib.parse.urlparse(files[0]["uri"]).path))
    assert path.read_bytes() == b"synthetic"
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="attached bytes"):
        prompt_parts([{"type": "image_url", "image_url": {"url": "file:///etc/passwd"}}])


@pytest.mark.parametrize("libc,target", [("glibc", "linux-x64-baseline"), ("musl", "linux-x64-baseline-musl")])
def test_download_uses_the_process_libc_even_when_compatibility_loaders_exist(monkeypatch, libc, target):
    from luna_core.opencode_install import release_target
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr("platform.libc_ver", lambda: (libc, ""))
    assert release_target() == target


@pytest.mark.parametrize("corrupt,symlink", [(False, False), (True, False), (False, True)])
def test_installer_verifies_archive_before_publishing(tmp_path, monkeypatch, corrupt, symlink):
    import base64
    import hashlib
    import tarfile
    from luna_core import opencode_install as installer
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
        member = tarfile.TarInfo("package/bin/opencode")
        if symlink:
            member.type, member.linkname = tarfile.SYMTYPE, "/etc/passwd"
            bundle.addfile(member)
        else:
            member.size = len(b"synthetic binary")
            bundle.addfile(member, io.BytesIO(b"synthetic binary"))
    payload = archive.getvalue()
    expected = b"incorrect" if corrupt else hashlib.sha512(payload).digest()
    monkeypatch.setattr(installer, "find_binary", lambda *args: None)
    monkeypatch.setattr(installer, "release_target", lambda: "test")
    monkeypatch.setattr(installer, "RELEASES", {"targets": {"test": {"tarball": "https://example.invalid/release", "integrity": "sha512-" + base64.b64encode(expected).decode()}}})
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(payload))
    monkeypatch.setattr(installer, "check_binary", lambda *args: installer.VERSION)
    if corrupt or symlink:
        with pytest.raises(RuntimeError, match="integrity|regular executable"):
            installer.install(tmp_path)
        assert not list(tmp_path.glob("bin/**/opencode"))
    else:
        binary, version = installer.install(tmp_path)
        assert binary.read_bytes() == b"synthetic binary" and version == installer.VERSION
        assert os.access(binary, os.X_OK)
    assert not list(tmp_path.glob(".install-*"))
