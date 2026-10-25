"""The same product, profile, identity and capabilities on every public launch path."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from hermes_cli import product_runtime


def test_fresh_home_and_named_profile_get_companion_defaults(tmp_path, monkeypatch):
    from hermes_cli.config import ensure_hermes_home
    from hermes_cli.profiles import create_profile
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    ensure_hermes_home()
    primary = yaml.safe_load((tmp_path / 'config.yaml').read_text())
    assert primary['model']['provider'] == 'opencode-engine'
    assert primary['model']['default'] == ''
    assert primary['memory']['provider'] == 'luna-memory'
    assert (tmp_path / 'SOUL.md').read_text().startswith('# Companion')
    secondary = create_profile('synthetic-companion', no_skills=True)
    child = yaml.safe_load((secondary / 'config.yaml').read_text())
    assert child['model']['provider'] == 'opencode-engine'
    assert child['memory']['provider'] == 'luna-memory'
    a = json.loads((tmp_path / 'honcho.json').read_text())['hosts']['hermes']['workspace']
    b = json.loads((secondary / 'honcho.json').read_text())['hosts']['hermes']['workspace']
    assert a != b
    assert (secondary / 'SOUL.md').read_text().startswith('# Companion')


def test_unmodified_engine_default_is_migrated_but_custom_character_is_kept(tmp_path, monkeypatch):
    from hermes_cli.config import _ensure_default_soul_md
    from hermes_cli.default_soul import DEFAULT_SOUL_MD
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'SOUL.md').write_text(DEFAULT_SOUL_MD)
    _ensure_default_soul_md(tmp_path)
    assert (tmp_path / 'SOUL.md').read_text().startswith('# Companion')
    (tmp_path / 'SOUL.md').write_text('# Nova\n\nCustom voice.\n')
    _ensure_default_soul_md(tmp_path)
    assert (tmp_path / 'SOUL.md').read_text() == '# Nova\n\nCustom voice.\n'


def test_child_launch_pins_code_interpreter_home_and_ignores_foreign_tui(tmp_path, monkeypatch):
    from hermes_cli.main_tui_launch import _apply_tui_python_env
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    env = {'HERMES_HOME':str(tmp_path), 'LUNA_HOME':'/foreign/hermes',
           'HERMES_PYTHON':'/usr/bin/python3','HERMES_PYTHON_SRC_ROOT':'/tmp',
           'HERMES_TUI_DIR':'/foreign/hermes/ui-tui','PYTHONPATH':'/foreign/hermes'}
    _apply_tui_python_env(env)
    assert env['HERMES_HOME'] == env['LUNA_HOME'] == str(tmp_path)
    assert env['HERMES_PYTHON_SRC_ROOT'] == str(product_runtime.ROOT)
    assert '/foreign/hermes' not in env['PYTHONPATH']
    assert 'HERMES_TUI_DIR' not in env


def test_empty_selected_model_does_not_bootstrap_a_vendor_account(tmp_path, monkeypatch):
    from hermes_cli import free_tier_bootstrap, anon_auth
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setattr(anon_auth, 'ensure_portal_identity', lambda *a, **kw: pytest.fail('No implicit vendor signup'))
    (tmp_path / 'config.yaml').write_text('model: {provider: opencode-engine, default: ""}\nluna: {}\n')
    free_tier_bootstrap.reset_for_tests()
    record = free_tier_bootstrap.run_bootstrap(announce=False)
    assert not record.provider_configured and not record.has_identity
    assert not (tmp_path / 'auth.json').exists()
    free_tier_bootstrap.reset_for_tests()


def test_companion_plugins_and_memory_are_bundled_for_unlinked_profiles(tmp_path, monkeypatch):
    from hermes_cli.plugins import PluginManager
    from plugins.memory import find_provider_dir
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text('luna: {}\nplugins: {enabled: []}\n')
    manager = PluginManager()
    manifests = manager._collect_directory_manifests()
    names = {manifest.name for manifest in manifests}
    assert {'luna-room','luna-memory','luna-ambient','luna-logger'} <= names
    assert find_provider_dir('luna-memory') == product_runtime.ROOT / 'luna/plugins/luna-memory'


def test_explicit_empty_dashboard_tools_do_not_enable_all_tools(tmp_path, monkeypatch):
    from tui_gateway import server
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text('luna: {}\nagent: {coding_context: off}\nplatform_toolsets: {cli: []}\n')
    monkeypatch.delenv('HERMES_TUI_TOOLSETS', raising=False)
    monkeypatch.setattr(server, '_gui_surface_toolsets', lambda platform: set())
    assert server._load_enabled_toolsets('tui') == []


def test_importing_cloud_binding_helpers_does_not_install_optional_providers():
    source = """
from tools import lazy_deps
calls = []
def forbidden(*args, **kwargs):
    calls.append((args, kwargs))
lazy_deps.ensure = forbidden
import agent.bedrock_adapter
import agent.vertex_adapter
assert not calls, 'Importing a helper cannot install optional provider dependencies'
"""
    subprocess.run([sys.executable, '-c', source], check=True, timeout=20)
