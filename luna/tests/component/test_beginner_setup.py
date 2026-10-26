"""Setup choices and Honcho controls must affect the real runtime, not just UI state."""
from pathlib import Path
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def setup_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    source = Path(__file__).resolve().parents[3]
    (tmp_path / "config.yaml").write_text((source / "luna/config/config.yaml.luna").read_text(encoding="utf-8"), encoding="utf-8")
    from hermes_cli.product_runtime import seed_home
    seed_home(tmp_path)
    return tmp_path


def test_optional_choices_survive_reload_without_memory_or_wake_probes(setup_home, monkeypatch):
    from luna_cli import onboarding
    from luna_core import config_read
    monkeypatch.setitem(onboarding._CHECKS, "provider", lambda: {"status": "done", "configured": True})
    monkeypatch.setitem(onboarding._CHECKS, "honcho", lambda: pytest.fail("Skipped memory performed a health probe"))
    monkeypatch.setitem(onboarding._CHECKS, "wake_test", lambda: {"status": "todo"})
    onboarding.set_choice("honcho", "skipped")
    result = onboarding.set_choice("wake_test", "skipped")
    assert {s["id"]: s["status"] for s in result["steps"]}["honcho"] == "skipped"
    assert config_read.load_config()["memory"]["memory_enabled"] is False
    assert config_read.load_config()["luna"]["ambient"]["enabled"] is False
    assert config_read.load_config()["luna"]["logger"]["sync_honcho"] is False
    # State comes from disk, not the current React/module instance.
    assert {s["id"]: s["status"] for s in onboarding.step_report()["steps"]}["wake_test"] == "skipped"


@pytest.mark.parametrize("value", ["http://127.0.0.1:8042/v1", "off", "001", "دوست: مهربون\nخط بعدی"])
def test_nested_config_strings_round_trip_without_document_markers(value):
    from luna_core.configedit import write_config_value
    import yaml
    text = write_config_value("honcho:\n  baseUrl: old\n  contextTokens: 2000\n", ["honcho", "baseUrl"], value)
    assert yaml.safe_load(text) == {"honcho": {"baseUrl": value, "contextTokens": 2000}}


@pytest.mark.parametrize("explicit_canonical_path", [False, True])
def test_dashboard_dialectic_controls_override_old_json_defaults(setup_home, explicit_canonical_path):
    from luna_core import settings
    from luna_core.configedit import write_config_value
    from luna_cli.memory_settings import report
    from plugins.memory.honcho.client import HonchoClientConfig
    client_path = setup_home / "honcho.json"
    previous = json.loads(client_path.read_text())
    previous["hosts"]["hermes"]["userPeerAliases"] = {"fixture-id": "fixture-peer"}
    client_path.write_text(json.dumps(previous))
    path = setup_home / "config.yaml"
    with settings.transaction():
        text = write_config_value(settings.read(path), ["honcho", "dialecticCadence"], 13)
        text = write_config_value(text, ["honcho", "dialecticReasoningLevel"], "medium")
        text = write_config_value(text, ["honcho", "recallMode"], "context")
        settings.write(path, text)
    actual = HonchoClientConfig.from_global_config(config_path=setup_home / "honcho.json" if explicit_canonical_path else None)
    assert (actual.dialectic_cadence, actual.dialectic_reasoning_level, actual.recall_mode) == (13, "medium", "context")
    panel = {f["key"]: f["value"] for f in report()["fields"]}
    assert panel["dialecticCadence"] == actual.dialectic_cadence
    assert panel["dialecticReasoningLevel"] == actual.dialectic_reasoning_level
    assert "api_key" not in report()["status"]
    # Registry-owned identity entries are retained, never rewritten as tuning.
    assert json.loads((setup_home / "honcho.json").read_text())["hosts"]["hermes"]["userPeerAliases"] == {"fixture-id": "fixture-peer"}


def test_fallback_defaults_preserve_existing_json_tuning_and_connection(setup_home):
    from plugins.memory.honcho.client import HonchoClientConfig
    from luna_core.honcho import connection_settings
    (setup_home / "config.yaml").write_text("memory: {provider: luna-memory, memory_enabled: true}\n")
    path = setup_home / "honcho.json"
    existing = json.loads(path.read_text())
    existing["baseUrl"] = "http://127.0.0.1:32123"
    existing["hosts"]["hermes"].update(dialecticCadence=17, dialecticReasoningLevel="low", workspace="existing-workspace")
    path.write_text(json.dumps(existing))
    actual = HonchoClientConfig.from_global_config()
    assert actual.dialectic_cadence == 17
    assert actual.dialectic_reasoning_level == "low"
    assert actual.base_url == connection_settings()["base_url"] == "http://127.0.0.1:32123"
    assert actual.workspace_id == "existing-workspace"


def test_settings_lock_is_reentrant_and_excludes_other_processes(setup_home):
    from hermes_cli.config_lock import settings_lock
    script = "from pathlib import Path; from hermes_cli._file_lock import acquire; f=Path(__import__('sys').argv[1]).open('a+'); acquire(f,blocking=False)"
    with settings_lock(setup_home), settings_lock(setup_home):
        result = subprocess.run([sys.executable, "-c", script, str(setup_home / ".settings.lock")], capture_output=True, text=True)
        assert result.returncode != 0 and "BlockingIOError" in result.stderr
    assert subprocess.run([sys.executable, "-c", script, str(setup_home / ".settings.lock")], capture_output=True).returncode == 0


def test_native_reasoning_validates_schema_and_follows_changed_companion(setup_home, monkeypatch):
    from luna_core import memory_reasoning, config_read
    from luna_core import opencode_aux
    (setup_home / "SOUL.md").write_text("PRIVATE PERSONA SENTINEL")
    seen = []
    replies = iter(["not JSON", '{"ok":true}', '{"ok":true}'])
    class Client:
        def __init__(self, model): self.model = model; self.chat = SimpleNamespace(completions=self)
        def with_options(self, **kwargs): return self
        def close(self): pass
        def create(self, **kwargs):
            seen.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))], usage=None)
    monkeypatch.setattr(opencode_aux, "OpenCodeAuxClient", Client)
    monkeypatch.setattr(memory_reasoning, "route", lambda: {"provider": "opencode-engine", "source": "companion", "model": config_read.load_config()["model"]["default"]})
    def select(name):
        from luna_core.settings import transaction, read, write
        from luna_core.configedit import write_config_value
        with transaction(): write(setup_home / "config.yaml", write_config_value(read(setup_home / "config.yaml"), ["model", "default"], name))
    body = {"messages": [{"role": "user", "content": "Synthetic memory evidence"}],
            "response_format": {"type": "json_schema", "json_schema": {"schema": {"type": "object", "properties": {"ok": {"const": True}}, "required": ["ok"]}}}}
    select("opencode/fixture-one")
    assert json.loads(memory_reasoning.complete(body)["choices"][0]["message"]["content"]) == {"ok": True}
    select("opencode/fixture-two")
    assert memory_reasoning.complete(body)["model"] == "opencode/fixture-two"
    assert len(seen) == 3 and seen[0]["model"] == "opencode/fixture-one"
    assert "PRIVATE PERSONA SENTINEL" not in json.dumps(seen)
    assert all("tools" not in call for call in seen)
    with pytest.raises(ValueError, match="without tools"):
        memory_reasoning.complete({**body, "tools": [{"name": "terminal"}]})


def test_populated_unknown_embedding_stack_is_not_reconfigured(setup_home, monkeypatch):
    from luna_core import managed_memory, docker_setup
    stack = setup_home / "honcho"; stack.mkdir()
    original = "EMBEDDING_MODEL_CONFIG__MODEL='old-model'\nEMBEDDING_VECTOR_DIMENSIONS='1536'\nPOSTGRES_PASSWORD='synthetic-kept'\n"
    (stack / ".env").write_text(original)
    monkeypatch.setattr(docker_setup, "ensure", lambda *a: pytest.fail("Existing index was touched"))
    result = managed_memory.setup()
    assert result["ok"] is False and "migration" in result["detail"]
    assert (stack / ".env").read_text() == original


def test_memory_bridge_requires_credential_and_rejects_token_id_arrays(setup_home):
    from fastapi.testclient import TestClient
    from luna_cli.memory_bridge import create_app
    from luna_core.embeddings import Embedder
    class Fake:
        def response(self, body):
            if not isinstance(body.get("input", [None])[0], str): raise ValueError("Text input required")
            return {"data": []}
    app = create_app("synthetic-bridge-key", {"nonce": "test", "home": str(setup_home)}, setup_home / "ready.json", embedder=Fake())
    with TestClient(app) as client:
        assert client.get("/health").status_code == 401
        assert client.get("/health", headers={"Authorization": "Bearer synthetic-bridge-key"}).json()["nonce"] == "test"
        assert client.post("/v1/embeddings", json={"input": [[123]]}).status_code == 401
        # Authentication never grants access to a disabled optional feature.
        assert client.post("/v1/embeddings", json={"input": [[123]]}, headers={"Authorization": "Bearer synthetic-bridge-key"}).status_code == 503


def test_skipped_memory_check_does_not_contact_any_server(setup_home, monkeypatch):
    from luna_core import readiness, honcho
    monkeypatch.setattr(honcho.HonchoStore, "client", lambda *a: pytest.fail("Skipped memory contacted a server"))
    assert readiness.verify_memory()["ok"] is False


@pytest.mark.parametrize("sdk_client", [False, True])
def test_memory_reasoning_accepts_provider_client_protocols(setup_home, monkeypatch, sdk_client):
    from luna_core import memory_reasoning
    from hermes_cli import runtime_provider
    from agent import auxiliary_client
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
                               usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10))
    # Codex/Anthropic adapters expose completions, but not OpenAI.with_options.
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    options = []
    if sdk_client:
        client.with_options = lambda **kwargs: (options.append(kwargs) or client)
    monkeypatch.setattr(memory_reasoning, "route", lambda: {
        "provider": "openai-codex", "source": "companion", "model": "fixture-subscription", "base_url": "", "key_env": ""})
    monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", lambda **kwargs: {"provider": "openai-codex"})
    monkeypatch.setattr(auxiliary_client, "resolve_provider_client", lambda *args, **kwargs: (client, "fixture-subscription"))
    result = memory_reasoning.complete({"messages": [{"role": "user", "content": "Synthetic evidence"}], "max_tokens": 32})
    assert result["usage"] == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
    assert result["choices"][0]["message"]["content"] == '{"ok":true}'
    assert calls[0]["timeout"] == 180 and calls[0]["max_tokens"] == 32
    assert options == ([{"timeout": 180, "max_retries": 0}] if sdk_client else [])
    assert "tools" not in calls[0]


def test_memory_restore_starts_containers_when_bridge_port_is_unchanged(setup_home, monkeypatch):
    from luna_core import managed_memory, memory_worker, config_read, data_ops, memory_network
    from luna_cli import onboarding
    stack = setup_home / "honcho"; stack.mkdir()
    (stack / ".embedding-contract.json").write_text("{}")
    (stack / ".env").write_text("DERIVER_MODEL_CONFIG__OVERRIDES__BASE_URL=http://127.0.0.1:34567/v1\n")
    monkeypatch.setattr(config_read, "section", lambda *args, **kwargs: "enabled")
    monkeypatch.setattr(managed_memory, "_contract", lambda path: None)
    monkeypatch.setattr(memory_worker, "ensure", lambda: {"port": 34567})
    monkeypatch.setattr(memory_network, "worker_url", lambda port: f"http://127.0.0.1:{port}/v1")
    monkeypatch.setattr(onboarding, "_seed_honcho_env", lambda *args, **kwargs: pytest.fail("Unchanged route must not rewrite credentials"))
    monkeypatch.setattr(data_ops, "compose_command", lambda *args: ["owned-memory-up"])
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (calls.append(args[0]) or SimpleNamespace(returncode=0)))
    managed_memory._restores.clear()
    managed_memory.restore()
    assert calls == [["owned-memory-up"]]


def test_anthropic_auxiliary_adapter_forwards_memory_timeout(monkeypatch):
    from agent import anthropic_adapter, transports
    from agent.auxiliary_client import _AnthropicCompletionsAdapter
    captured = {}
    monkeypatch.setattr(anthropic_adapter, "build_anthropic_kwargs", lambda **kwargs: {"model": kwargs["model"]})
    def send(client, kwargs, **options):
        captured.update(kwargs)
        return SimpleNamespace(usage=None)
    monkeypatch.setattr(anthropic_adapter, "create_anthropic_message", send)
    monkeypatch.setattr(transports, "get_transport", lambda name: SimpleNamespace(normalize_response=lambda response, **options:
        SimpleNamespace(content="OK", tool_calls=None, reasoning=None, finish_reason="stop")))
    client = _AnthropicCompletionsAdapter(SimpleNamespace(base_url="https://api.anthropic.com"), "fixture-model")
    assert client.create(messages=[], timeout=180).choices[0].message.content == "OK"
    assert captured["timeout"] == 180


def test_failed_memory_restore_can_retry_immediately(setup_home, monkeypatch):
    from luna_core import managed_memory, memory_worker, config_read, data_ops, memory_network
    stack = setup_home / "honcho"; stack.mkdir()
    (stack / ".embedding-contract.json").write_text("{}")
    (stack / ".env").write_text("DERIVER_MODEL_CONFIG__OVERRIDES__BASE_URL=http://127.0.0.1:34567/v1\n")
    monkeypatch.setattr(config_read, "section", lambda *args, **kwargs: "enabled")
    monkeypatch.setattr(managed_memory, "_contract", lambda path: None)
    monkeypatch.setattr(memory_worker, "ensure", lambda: {"port": 34567})
    monkeypatch.setattr(memory_network, "worker_url", lambda port: f"http://127.0.0.1:{port}/v1")
    monkeypatch.setattr(data_ops, "compose_command", lambda *args: ["owned-memory-up"])
    calls = []
    def run(*args, **kwargs):
        calls.append(args[0])
        return SimpleNamespace(returncode=1 if len(calls)==1 else 0)
    monkeypatch.setattr(subprocess, "run", run)
    managed_memory._restores.clear()
    managed_memory.restore()
    managed_memory.restore()
    assert len(calls) == 2


def test_memory_disable_waits_for_inflight_restore(setup_home, monkeypatch):
    import threading
    from luna_core import managed_memory, memory_worker, config_read, data_ops, memory_network
    stack = setup_home / "honcho"; stack.mkdir()
    (stack / ".embedding-contract.json").write_text("{}")
    (stack / ".env").write_text("DERIVER_MODEL_CONFIG__OVERRIDES__BASE_URL=http://127.0.0.1:34567/v1\n")
    enabled = ["enabled"]; started=threading.Event(); proceed=threading.Event(); disabled=threading.Event(); calls=[]
    monkeypatch.setattr(config_read, "section", lambda *args, **kwargs: enabled[0])
    monkeypatch.setattr(managed_memory, "_contract", lambda path: None)
    def ensure():
        started.set(); assert proceed.wait(5); return {"port":34567}
    monkeypatch.setattr(memory_worker, "ensure", ensure)
    monkeypatch.setattr(memory_worker, "stop", lambda: None)
    monkeypatch.setattr(memory_network, "worker_url", lambda port: f"http://127.0.0.1:{port}/v1")
    monkeypatch.setattr(data_ops, "compose_command", lambda stack, *args: list(args))
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: (calls.append(args[0]) or SimpleNamespace(returncode=0)))
    def disable():
        managed_memory.disable(); disabled.set()
    managed_memory._restores.clear()
    first=threading.Thread(target=managed_memory.restore); second=threading.Thread(target=disable)
    first.start(); assert started.wait(5)
    try:
        enabled[0]="skipped"; second.start()
        assert not disabled.wait(.1)
    finally:
        proceed.set(); first.join(5); second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert calls[-1] == "stop"
