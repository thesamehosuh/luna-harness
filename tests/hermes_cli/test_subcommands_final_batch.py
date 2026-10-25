"""Smoke tests for the final batch of subcommand builders extracted from main().

Kept groups either import their handler from a sibling module or take the handler
by injection. (moa/worktree/bundles/curator/pets/journey/computer-use/whatsapp were
removed with the non-product CLI surface in P5.)
"""

from __future__ import annotations

import argparse

import pytest

from hermes_cli.subcommands.browser import build_browser_parser
from hermes_cli.subcommands.checkpoints import build_checkpoints_parser
from hermes_cli.subcommands.completion import build_completion_parser
from hermes_cli.subcommands.egress import build_egress_parser
from hermes_cli.subcommands.fallback import build_fallback_parser
from hermes_cli.subcommands.migrate import build_migrate_parser
from hermes_cli.subcommands.secrets import build_secrets_parser
from hermes_cli.subcommands.sessions import build_sessions_parser


def _tree():
    parser = argparse.ArgumentParser(prog="hermes")
    return parser, parser.add_subparsers(dest="command")


SELF_CONTAINED = [
    ("fallback", build_fallback_parser, ["fallback", "add"]),
    ("browser", build_browser_parser, ["browser", "close-profile"]),
    ("secrets", build_secrets_parser, ["secrets"]),
    ("egress", build_egress_parser, ["egress"]),
    ("migrate", build_migrate_parser, ["migrate", "xai", "--apply"]),
    ("checkpoints", build_checkpoints_parser, ["checkpoints"]),
]


@pytest.mark.parametrize("name,builder,argv", SELF_CONTAINED, ids=[c[0] for c in SELF_CONTAINED])
def test_self_contained_builders_attach(name, builder, argv):
    parser, sub = _tree()
    builder(sub)
    ns = parser.parse_args(argv)
    assert ns.command == name
    assert callable(getattr(ns, "func", None)) or name in ("checkpoints",)


def test_sessions_injects_handler_and_threads_parser():
    parser, sub = _tree()
    calls = []
    build_sessions_parser(sub, cmd_sessions=lambda a, **kw: calls.append((a, kw)) or 0)
    ns = parser.parse_args(["sessions", "prune", "--older-than", "2d", "--dry-run"])
    assert ns.sessions_action == "prune" and ns.older_than == "2d" and ns.dry_run is True
    assert ns.func(ns) == 0
    (a, kw), = calls
    assert a is ns
    assert kw["sessions_parser"].prog.endswith("sessions")


def test_completion_passes_top_level_parser():
    parser, sub = _tree()
    got = {}
    build_completion_parser(sub, cmd_completion=lambda a, p: got.update(a=a, p=p), parser=parser)
    ns = parser.parse_args(["completion", "zsh"])
    ns.func(ns)
    assert got["p"] is parser and got["a"].shell == "zsh"
