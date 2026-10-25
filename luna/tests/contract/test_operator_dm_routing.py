"""Contract: operator-DM routing (ex-patch 0010) and cron group envelope stripping (ex-patch 0011).

Engine edits are folded into the tree (recorded in ``luna/docs/engine-vendor.md``), so this tier
asserts the wiring as it ships in the source files (the same source-string style as
``test_private_symbol_surface.py``). Behaviour is covered in ``luna/tests/unit``.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_routing_policy_module_ships_in_the_tree():
    text = _read("gateway/operator_route.py")
    assert "def operator_status_target" in text
    assert "def operator_notice_target" in text
    assert "def register_forwarded_prompt" in text
    assert "def resolve_forwarded_session_key" in text


def test_routing_hooks_the_turn_status_surface_and_notices():
    turn = _read("gateway/run_turn.py")
    assert "operator_status_target" in turn
    assert "turn_ctx._status_chat_id" in turn
    notices = _read("gateway/run_notifications.py")
    assert "operator_notice_target" in notices


def test_routing_registers_and_correlates_prompts():
    runner = _read("gateway/run_turn_runner.py")
    assert runner.count("register_forwarded_prompt") >= 2  # approval + clarify
    inbound = _read("gateway/run_inbound.py")
    assert "_hm_operator_prompt_reply" in inbound
    assert "resolve_forwarded_session_key" in inbound
    assert "_hm_operator_approval_reply" in inbound


def test_cron_is_exempt_from_operator_routing():
    # The routing policy must never live in cron/ (cron owns its delivery policy), and the policy
    # carries an explicit cron-origin guard.
    assert "origin" in _read("gateway/operator_route.py")
    assert 'origin == "cron"' in _read("gateway/operator_route.py")


def test_cron_strips_the_envelope_for_groups_only():
    delivery = _read("cron/scheduler_delivery.py")
    assert "_strip_cron_envelope" in delivery
    assert "_target_is_group_surface" in delivery
    assert "target_content" in delivery
    # The per-target send (both lanes) uses the stripped text; the envelope composition itself is
    # untouched.
    assert delivery.count("t, target_content, media_files") == 2
    assert "Cronjob Response:" in delivery
    # Group cron text also gets the chat rhythm (cron bypasses transform_llm_output entirely).
    assert "_shape_cron_group_text" in delivery
    assert "chat_rhythm" in delivery
    assert "_shape_cron_group_text(_strip_cron_envelope(target_content))" in delivery
    # Origin now stores chat_type, and the group test tolerates jobs created before it did.
    assert 'get_session_env("HERMES_SESSION_CHAT_TYPE")' in _read("tools/cronjob_job_args.py")
    assert 'chat_id.startswith("-")' in delivery


def test_config_template_exposes_the_operator_dm_namespace():
    config = (REPO_ROOT / "luna" / "config" / "config.yaml.luna").read_text(encoding="utf-8")
    assert "operator_chat:" in config
    assert "telegram:" in config
    # The template documents the cron exemption so the placeholder is not mistaken for routing.
    notify_block = config[config.index("notify:"): config.index("logger:")]
    assert "cron" in notify_block.lower()
