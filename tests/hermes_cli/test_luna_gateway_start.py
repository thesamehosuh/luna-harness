"""Portable desktop start uses the existing gateway without requiring an OS service."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import hermes_cli.gateway as gateway
from hermes_cli import product_runtime


@pytest.mark.parametrize("service,system,windows,foreground", [
    (None, False, False, True),
    ("systemd", False, False, False),
    (None, True, False, False),
    (None, False, True, False),
])
def test_luna_gateway_start_selects_installed_service_or_direct_run(monkeypatch, service, system, windows, foreground):
    monkeypatch.setattr(product_runtime, "enabled", lambda: True)
    monkeypatch.setattr(gateway, "_guard_named_profile_under_multiplexer", lambda **_: None)
    monkeypatch.setattr(gateway, "_dispatch_via_service_manager_if_s6", lambda *_: False)
    monkeypatch.setattr(gateway, "_installed_service_kind", lambda: service)
    monkeypatch.setattr(gateway, "is_windows", lambda: windows)
    monkeypatch.setattr(gateway, "is_termux", lambda: False)
    monkeypatch.setattr(gateway, "_service_backend", lambda: "windows" if windows else "systemd")
    run, service_call = Mock(), Mock()
    monkeypatch.setattr(gateway.os, "execv", run)
    monkeypatch.setattr(gateway, "_current_profile_name", lambda: "default")
    monkeypatch.setattr(gateway, "_gateway_run_args_for_profile", lambda _: ["/runtime/venv/bin/python", "-m", "luna_cli.main", "gateway", "run", "--replace"])
    monkeypatch.setattr(gateway, "_service_call", service_call)
    gateway._cmd_start(SimpleNamespace(system=system, all=False, force=False))
    if foreground:
        run.assert_called_once_with("/runtime/venv/bin/python", ["/runtime/venv/bin/python", "-m", "luna_cli.main", "gateway", "run"])
        service_call.assert_not_called()
    else:
        run.assert_not_called()
        service_call.assert_called_once_with("windows" if windows else "systemd", "start", system)

@pytest.mark.parametrize('command', [
    '/runtime/venv/bin/python -m luna_cli.main gateway run',
    '/runtime/venv/bin/python /runtime/luna/lib/luna_cli/main.py gateway run',
    'luna gateway run',
    '"C:\\Program Files\\Luna\\luna.exe" gateway run',
])
def test_luna_gateway_entrypoints_are_recognized_by_status_and_stop(command):
    from gateway.status import looks_like_gateway_command_line, looks_like_gateway_runtime_command_line
    assert looks_like_gateway_command_line(command)
    assert looks_like_gateway_runtime_command_line(command)

@pytest.mark.parametrize('command', [
    'python -m luna_cli.main gateway status',
    'python -m luna_cli.main gateway stop',
    'python -m tui_gateway',
    'python -c "print(\'luna_cli.main gateway run\')"',
])
def test_luna_status_does_not_claim_unrelated_or_transient_commands(command):
    from gateway.status import looks_like_gateway_runtime_command_line
    assert not looks_like_gateway_runtime_command_line(command)
