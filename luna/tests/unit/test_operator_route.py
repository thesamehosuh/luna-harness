"""Unit coverage for the operator-DM routing policy (Luna engine edit, ex-patch 0010).

The module ships in the tree at ``gateway/operator_route.py`` (recorded in
``luna/docs/engine-vendor.md``), so these tests load the file directly by path. Policy is pure:
no gateway import is needed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_REL = "gateway/operator_route.py"


def _load_operator_route():
    path = REPO_ROOT / MODULE_REL
    spec = importlib.util.spec_from_file_location("gateway_operator_route", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def route():
    return _load_operator_route()


class _Source:
    def __init__(self, chat_type, chat_id="group-1", platform="telegram"):
        self.chat_type = chat_type
        self.chat_id = chat_id
        self.platform = platform


def _config(chat_id="999"):
    return {"luna": {"notify": {"operator_chat": {"telegram": chat_id}}}}


def test_group_surface_detection(route):
    assert route.is_group_surface(_Source("group"))
    assert route.is_group_surface(_Source("supergroup"))
    assert route.is_group_surface(_Source("channel"))
    assert route.is_group_surface(_Source("forum"))
    assert not route.is_group_surface(_Source("dm"))
    assert not route.is_group_surface(_Source("private"))
    assert not route.is_group_surface(_Source(None))


def test_group_is_routed_to_operator_dm(route):
    assert route.operator_status_target(_Source("group"), user_config=_config()) == "999"
    assert route.operator_notice_target(_Source("channel"), user_config=_config()) == "999"


def test_dm_surface_is_never_routed(route):
    assert route.operator_status_target(_Source("dm"), user_config=_config()) is None


def test_cron_origin_is_exempt(route):
    assert route.operator_status_target(
        _Source("group"), user_config=_config(), origin="cron") is None
    assert route.operator_notice_target(
        _Source("group"), user_config=_config(), origin="cron") is None


@pytest.mark.parametrize("placeholder", ["0", "", "  ", "none", "off"])
def test_placeholder_operator_chat_disables_routing(route, placeholder):
    assert route.operator_status_target(_Source("group"), user_config=_config(placeholder)) is None


def test_missing_or_malformed_config_disables_routing(route):
    assert route.operator_status_target(_Source("group"), user_config={}) is None
    assert route.operator_status_target(_Source("group"), user_config={"luna": None}) is None


def test_unavailable_ambient_config_disables_routing(route, monkeypatch):
    # user_config=None means "defer to the ambient gateway config". Block that lookup so the
    # assertion cannot depend on the developer's own config.yaml, which may legitimately define
    # an operator chat id.
    monkeypatch.setitem(sys.modules, "gateway.warning_notifications", None)
    assert route.operator_status_target(_Source("group"), user_config=None) is None


def test_same_chat_target_never_routes(route):
    # A misconfigured operator chat equal to the group must not cause a self-send loop.
    assert route.operator_status_target(
        _Source("group", chat_id="999"), user_config=_config()) is None


def test_register_only_when_routed(route):
    op = _Source("dm", chat_id="999")
    registered = _Source("group", chat_id="grp-a")
    # Not routed (target == source chat) -> no-op.
    route.register_forwarded_prompt(registered, "sess-a", target_chat_id="grp-a")
    assert route.resolve_forwarded_session_key(op, still_pending=lambda _k: True) is None
    # Missing session key -> no-op.
    route.register_forwarded_prompt(registered, "", target_chat_id="999")
    assert route.resolve_forwarded_session_key(op, still_pending=lambda _k: True) is None


def test_forwarded_prompt_fifo_and_stale_pruning(route):
    op = _Source("dm", chat_id="998")
    group = _Source("group", chat_id="grp-b")
    route.register_forwarded_prompt(group, "sess-1", target_chat_id="998")
    route.register_forwarded_prompt(group, "sess-2", target_chat_id="998")
    # Oldest still-pending wins.
    assert route.resolve_forwarded_session_key(op, still_pending=lambda _k: True) == "sess-1"
    # A resolved gate is pruned and no longer captures replies.
    assert route.resolve_forwarded_session_key(
        op, still_pending=lambda k: k == "sess-2") == "sess-2"
    assert route.resolve_forwarded_session_key(op, still_pending=lambda _k: False) is None
    assert route.resolve_forwarded_session_key(op, still_pending=lambda _k: True) is None


def test_forwarded_prompt_liveness_failure_is_not_fatal(route):
    op = _Source("dm", chat_id="997")
    group = _Source("group", chat_id="grp-c")
    route.register_forwarded_prompt(group, "sess-x", target_chat_id="997")

    def _boom(_key):
        raise RuntimeError("gate store unavailable")

    assert route.resolve_forwarded_session_key(op, still_pending=_boom) is None
