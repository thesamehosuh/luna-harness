"""Smoke tests for extracted subcommand builders.

Confirms each kept builder attaches its subcommand and wires func to the injected handler.
(The first two extraction batches' non-product subcommands were removed in P5 — those case
lists are gone with them.)
"""

from __future__ import annotations

import argparse

import pytest

from hermes_cli.subcommands.auth import build_auth_parser
from hermes_cli.subcommands.backup import build_backup_parser
from hermes_cli.subcommands.config import build_config_parser
from hermes_cli.subcommands.doctor import build_doctor_parser
from hermes_cli.subcommands.gui import build_gui_parser
from hermes_cli.subcommands.hooks import build_hooks_parser
from hermes_cli.subcommands.import_cmd import build_import_cmd_parser
from hermes_cli.subcommands.login import build_login_parser
from hermes_cli.subcommands.logout import build_logout_parser
from hermes_cli.subcommands.logs import build_logs_parser
from hermes_cli.subcommands.model import build_model_parser
from hermes_cli.subcommands.security import build_security_parser
from hermes_cli.subcommands.setup import build_setup_parser
from hermes_cli.subcommands.status import build_status_parser
from hermes_cli.subcommands.uninstall import build_uninstall_parser
from hermes_cli.subcommands.update import build_update_parser


def _h(name):
    def handler(args):  # pragma: no cover - identity only
        return name
    handler.__name__ = f"cmd_{name}"
    return handler


# (subcommand_name, builder, handler_kwargs, sample_argv)
SINGLE_HANDLER_CASES = [
    ("model", build_model_parser, "cmd_model", ["model"]),
    ("setup", build_setup_parser, "cmd_setup", ["setup"]),
    ("login", build_login_parser, "cmd_login", ["login"]),
    ("logout", build_logout_parser, "cmd_logout", ["logout"]),
    ("auth", build_auth_parser, "cmd_auth", ["auth"]),
    ("status", build_status_parser, "cmd_status", ["status"]),
    ("hooks", build_hooks_parser, "cmd_hooks", ["hooks"]),
    ("doctor", build_doctor_parser, "cmd_doctor", ["doctor"]),
    ("security", build_security_parser, "cmd_security", ["security"]),
    ("backup", build_backup_parser, "cmd_backup", ["backup"]),
    ("import", build_import_cmd_parser, "cmd_import", ["import", "/tmp/x.zip"]),
    ("config", build_config_parser, "cmd_config", ["config"]),
    ("update", build_update_parser, "cmd_update", ["update"]),
    ("uninstall", build_uninstall_parser, "cmd_uninstall", ["uninstall"]),
    ("gui", build_gui_parser, "cmd_gui", ["gui"]),
    ("logs", build_logs_parser, "cmd_logs", ["logs"]),
]


@pytest.mark.parametrize("name,builder,kw,argv", SINGLE_HANDLER_CASES, ids=[c[0] for c in SINGLE_HANDLER_CASES])
def test_single_handler_builders_dispatch(name, builder, kw, argv):
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    handler = _h(name)
    builder(sub, **{kw: handler})
    ns = parser.parse_args(argv)
    assert ns.command == name
    assert ns.func is handler


def test_config_get_unset_subcommands_parse():
    """`hermes config get/unset` parse key args (and --json for get)."""
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    handler = _h("config")
    build_config_parser(sub, cmd_config=handler)

    ns = parser.parse_args(["config", "get", "terminal.backend", "--json"])
    assert ns.func is handler
    assert ns.config_command == "get"
    assert ns.key == "terminal.backend"
    assert ns.json is True

    ns = parser.parse_args(["config", "unset", "terminal.backend"])
    assert ns.func is handler
    assert ns.config_command == "unset"
    assert ns.key == "terminal.backend"


# ── deprecated `hermes login` fails gracefully, not with argparse error ────
#
# `hermes login` is a removed command; its handler (`login_command` in
# `hermes_cli/auth.py`) prints a deprecation notice pointing at `hermes auth` /
# `hermes model` and exits 0.  Two behavior contracts guard the UX:
#   1. ANY `--provider <value>` (including ones the user actually wants, like
#      `anthropic`) must parse and reach the handler — never crash in argparse
#      with `invalid choice` before the friendly redirect is printed (#24756).
#   2. The subcommand must not advertise itself in the parser help row.


def _login_parser():
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    build_login_parser(sub, cmd_login=_h("login"))
    return parser


def test_login_any_provider_reaches_handler():
    parser = _login_parser()
    ns = parser.parse_args(["login", "--provider", "anthropic"])
    assert ns.func is not None


def test_login_subparser_help_is_suppressed():
    """The deprecated `login` row must not appear in `hermes --help`.

    Must hold without leaking argparse's literal `==SUPPRESS==` placeholder,
    which `help=argparse.SUPPRESS` emits for a top-level subparser on 3.12+.
    The fix omits the `help=` kwarg entirely instead.
    """
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    build_login_parser(sub, cmd_login=_h("login"))
    help_text = parser.format_help()
    # The misleading old help string must be gone from the top-level usage.
    assert "Authenticate with an inference provider" not in help_text
    # And no leaked SUPPRESS placeholder row.
    assert "==SUPPRESS==" not in help_text
