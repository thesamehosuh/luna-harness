"""Unit coverage for cron group-envelope stripping (Luna engine edit, ex-patch 0011).

The helpers ship in the tree at ``cron/scheduler_delivery.py`` (recorded in
``luna/docs/engine-vendor.md``); this loads their source straight out of that file (the module
pulls heavy cron deps at import time).
"""

from __future__ import annotations

import ast
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DELIVERY_PY = REPO_ROOT / "cron" / "scheduler_delivery.py"
WANTED = (
    "_GROUP_CHAT_TYPES", "_target_is_group_surface", "_strip_cron_envelope",
    "_CRON_ENVELOPE_HEADER", "_CRON_ENVELOPE_DIVIDER", "_CRON_ENVELOPE_FOOTER",
)


def _load_helpers():
    src = DELIVERY_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    segments = []
    for node in tree.body:
        names = ()
        if isinstance(node, ast.FunctionDef):
            names = (node.name,)
        elif isinstance(node, ast.Assign):
            names = tuple(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = (node.target.id,)
        if set(names) & set(WANTED):
            segments.append(ast.get_source_segment(src, node))
    module = types.ModuleType("cron_envelope_helpers")
    exec(compile("\n\n".join(segments), "cron/scheduler_delivery.py", "exec"), module.__dict__)
    return module


@pytest.fixture(scope="module")
def helpers():
    return _load_helpers()


ENVELOPED = (
    "Cronjob Response: himeta-2049-tag\n"
    "(job_id: d87b19effe0a)\n"
    "-------------\n\n"
    "@m11nttiramisu today's agenda:\n"
    "• explain Himeta's lore to iris\n"
    "• Gartic Phone videos\n"
    "• language homework\n\n"
    "To stop or manage this job, send me a new message "
    '(e.g. "stop reminder himeta-2049-tag").'
)
EXPECTED = (
    "@m11nttiramisu today's agenda:\n"
    "• explain Himeta's lore to iris\n"
    "• Gartic Phone videos\n"
    "• language homework"
)


def test_strips_header_and_footer_keeping_only_the_response(helpers):
    assert helpers._strip_cron_envelope(ENVELOPED) == EXPECTED


def test_plain_text_is_untouched(helpers):
    assert helpers._strip_cron_envelope("just a response") == "just a response"
    assert helpers._strip_cron_envelope("") == ""
    assert helpers._strip_cron_envelope(None) is None


def test_response_containing_the_word_response_survives(helpers):
    body = EXPECTED
    wrapped = f"Cronjob Response: j\n(job_id: x)\n-------------\n\n{body}\n\nTo stop or manage this job, send me a new message (e.g. \"stop reminder j\")."
    assert helpers._strip_cron_envelope(wrapped) == body


class _Target:
    def __init__(self, *, origin_target, is_dm_target, origin_chat_type, chat_id="-100"):
        self.origin_target = origin_target
        self.is_dm_target = is_dm_target
        self.origin = {"chat_type": origin_chat_type}
        self.chat_id = chat_id


def test_group_targets_are_stripped(helpers):
    assert helpers._target_is_group_surface(
        _Target(origin_target=True, is_dm_target=False, origin_chat_type="group"))
    assert helpers._target_is_group_surface(
        _Target(origin_target=True, is_dm_target=False, origin_chat_type="supergroup"))
    # Explicit (non-origin) group target.
    assert helpers._target_is_group_surface(
        _Target(origin_target=False, is_dm_target=False, origin_chat_type=None, chat_id="-1003651996866"))
    # Regression: jobs created before origin captured chat_type — a negative id still reads as group.
    assert helpers._target_is_group_surface(
        _Target(origin_target=True, is_dm_target=False, origin_chat_type=None, chat_id="-1003651996866"))


def test_dm_targets_keep_the_envelope(helpers):
    assert not helpers._target_is_group_surface(
        _Target(origin_target=True, is_dm_target=True, origin_chat_type="dm", chat_id="12345"))
    assert not helpers._target_is_group_surface(
        _Target(origin_target=False, is_dm_target=True, origin_chat_type=None, chat_id="12345"))
    # Positive numeric with no chat_type = Telegram private chat; unknown shape stays untouched.
    assert not helpers._target_is_group_surface(
        _Target(origin_target=True, is_dm_target=False, origin_chat_type=None, chat_id="12345"))
    assert not helpers._target_is_group_surface(
        _Target(origin_target=False, is_dm_target=False, origin_chat_type=None, chat_id="D123SLACK"))
