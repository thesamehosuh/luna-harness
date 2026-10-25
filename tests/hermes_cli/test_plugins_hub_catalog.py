"""Plugins-hub / plugins-list catalog lookups stay offline.

Luna ships the plugin catalog empty and offline (PRODUCT_PLAN §4): the hub rebuild and
``hermes plugins list`` annotate rows from the in-tree kill list only — zero network
attempts, and never one request per installed plugin.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_cli import plugin_catalog as pc
from hermes_cli import plugins_cmd
from hermes_cli import web_server
import hermes_cli.config as _cfg_mod
import hermes_cli.web_server_dashboard as _web_server_dashboard
import hermes_cli.web_server_memory as _web_server_memory
from tools import registry as tools_registry


class _NoNetwork:
    """Fails the test on any network attempt from catalog code."""

    def __init__(self):
        self.attempts = 0

    def __call__(self, *args, **kwargs):
        self.attempts += 1
        raise AssertionError("the offline plugin catalog must not touch the network")


@pytest.fixture(autouse=True)
def _isolated_catalog(monkeypatch):
    tools_registry.invalidate_check_fn_cache()
    _web_server_dashboard._invalidate_plugins_hub_cache()
    yield
    tools_registry.invalidate_check_fn_cache()
    _web_server_dashboard._invalidate_plugins_hub_cache()


_PLUGIN_ROWS = [
    ("demo", "1.0.0", "demo plugin", "user", "/tmp/demo-plugin", "demo"),
    ("second", "0.2.0", "second plugin", "user", "/tmp/second-plugin", "second"),
    ("third", "0.3.0", "third plugin", "user", "/tmp/third-plugin", "third"),
]


def test_hub_rebuild_and_plugins_list_resolve_the_kill_list_offline(monkeypatch, tmp_path, capsys):
    """Both listing surfaces cost ZERO network attempts and still report an in-tree removal
    for every affected row."""
    unreachable = _NoNetwork()
    monkeypatch.setattr("httpx.get", unreachable, raising=False)
    monkeypatch.setattr(pc, "get_catalog_dir", lambda: tmp_path)
    (tmp_path / "removed.yaml").write_text("removed:\n- name: demo\n  reason: exfiltrated env vars\n")

    monkeypatch.setattr(web_server, "_get_dashboard_plugins", lambda force_rescan=False: [])
    monkeypatch.setattr(_web_server_memory, "_discover_memory_provider_statuses", lambda: [])
    monkeypatch.setattr(_cfg_mod, "get_hermes_home", lambda: Path("/tmp/hermes-home"))
    monkeypatch.setattr(_cfg_mod, "load_config", lambda: {"dashboard": {"hidden_plugins": []}})
    monkeypatch.setattr(plugins_cmd, "_discover_all_plugins", lambda: list(_PLUGIN_ROWS))
    monkeypatch.setattr(plugins_cmd, "_get_current_context_engine", lambda: "compressor")
    monkeypatch.setattr(plugins_cmd, "_get_current_memory_provider", lambda: "")
    monkeypatch.setattr(plugins_cmd, "_discover_context_engines", lambda: [])
    monkeypatch.setattr(plugins_cmd, "_get_disabled_set", lambda: set())
    monkeypatch.setattr(plugins_cmd, "_get_enabled_set", lambda: {"demo"})
    monkeypatch.setattr(plugins_cmd, "_read_manifest", lambda _path: {"provides_tools": []})
    monkeypatch.setattr(plugins_cmd, "_read_install_metadata", lambda: {})
    monkeypatch.setattr(tools_registry.registry, "get_entry", lambda _name: SimpleNamespace(check_fn=None))

    payload = _web_server_dashboard._merged_plugins_hub(force_refresh=True)
    by_name = {row["name"]: row["removed_reason"] for row in payload["plugins"]}
    assert by_name == {"demo": "exfiltrated env vars", "second": None, "third": None}

    plugins_cmd.cmd_list(argparse.Namespace(enabled=False, user=False, no_bundled=False, plain=False, json=True))
    rows = {row["name"]: row["removed"] for row in json.loads(capsys.readouterr().out)}
    assert rows == {"demo": "exfiltrated env vars", "second": None, "third": None}

    assert unreachable.attempts == 0
