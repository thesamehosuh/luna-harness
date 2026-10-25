"""Unit coverage for the queued-chain final reply anchor (Luna engine edit, ex-patch 0015).

The helper ships in the tree at ``gateway/platforms/base.py`` (recorded in
``luna/docs/engine-vendor.md``); this loads the function source straight out of that file and
execs it with the two base.py helpers it calls stubbed (base.py pulls heavy gateway deps).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_PY = REPO_ROOT / "gateway" / "platforms" / "base.py"


def _load_helper(anchor="111"):
    src = BASE_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    node = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_queued_terminal_reply_anchor"
    )
    source = ast.get_source_segment(src, node)
    ns = {
        "_platform_name": lambda p: p,
        "_reply_anchor_for_event": lambda event: anchor,
    }
    exec(compile(source, "gateway/platforms/base.py", "exec"), ns)
    return ns["_queued_terminal_reply_anchor"]


class _Source:
    def __init__(self, platform):
        self.platform = platform


class _Event:
    def __init__(self, platform):
        self.source = _Source(platform)


def test_terminal_queued_id_becomes_the_anchor():
    helper = _load_helper()
    event = _Event("telegram")
    assert helper(event, {"queued_terminal_inbound_id": "222"}) == "222"


def test_falls_back_when_nothing_to_override():
    helper = _load_helper()
    event = _Event("telegram")
    for response in ("plain", None, {}, {"queued_terminal_inbound_id": None}):
        assert helper(event, response) is None


def test_event_stash_wins_when_response_is_text():
    # The gateway handler returns text and stashes the id on the event; base.py must honour it.
    helper = _load_helper()
    event = _Event("telegram")
    event._luna_queued_reply_anchor = "333"
    assert helper(event, "just the text") == "333"


def test_only_telegram_is_rewritten():
    helper = _load_helper()
    assert helper(_Event("slack"), {"queued_terminal_inbound_id": "222"}) is None


def test_respects_unanchored_surfaces():
    # Topics / Slack handoffs have no reply anchor — keep that behavior.
    helper = _load_helper(anchor=None)
    assert helper(_Event("telegram"), {"queued_terminal_inbound_id": "222"}) is None


def test_ignores_implausible_ids():
    helper = _load_helper()
    assert helper(_Event("telegram"), {"queued_terminal_inbound_id": "not-a-message-id"}) is None
