"""Smoke tests for the Phase 2 follow-up subcommand builders (promoted handlers).

Confirms each kept builder attaches its subcommand and wires func to the injected
handler. (acp/insights/claw were removed with the non-product CLI surface in P5.)
"""

from __future__ import annotations

import argparse

import pytest

from hermes_cli.subcommands.mcp import build_mcp_parser
from hermes_cli.subcommands.memory import build_memory_parser
from hermes_cli.subcommands.pairing import build_pairing_parser
from hermes_cli.subcommands.plugins import build_plugins_parser
from hermes_cli.subcommands.skills import build_skills_parser
from hermes_cli.subcommands.tools import build_tools_parser


def _h(name):
    def handler(args):  # pragma: no cover - identity only
        return name
    handler.__name__ = f"cmd_{name}"
    return handler


# (subcommand, builder, handler_kwarg, sample argv that should dispatch to func)
CASES = [
    ("memory", build_memory_parser, "cmd_memory", ["memory"]),
    ("tools", build_tools_parser, "cmd_tools", ["tools"]),
    ("skills", build_skills_parser, "cmd_skills", ["skills"]),
    ("pairing", build_pairing_parser, "cmd_pairing", ["pairing"]),
    ("plugins", build_plugins_parser, "cmd_plugins", ["plugins"]),
    ("mcp", build_mcp_parser, "cmd_mcp", ["mcp"]),
]


@pytest.mark.parametrize("name,builder,kw,argv", CASES, ids=[c[0] for c in CASES])
def test_followup_builders_dispatch(name, builder, kw, argv):
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    handler = _h(name)
    builder(sub, **{kw: handler})
    ns = parser.parse_args(argv)
    assert ns.command == name
    assert ns.func is handler


def test_mcp_accepts_hooks_flag():
    # the mcp parser block uses the shared add_accept_hooks_flag helper (top level).
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    build_mcp_parser(sub, cmd_mcp=_h("mcp"))
    ns = parser.parse_args(["mcp", "--accept-hooks"])
    assert ns.accept_hooks is True
