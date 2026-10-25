"""Contract: the operator's tool policy and the cron guard rails.

Execution is **enabled** on Telegram by operator decision (the group is Luna's main interface);
the net for dangerous actions is the approval gate (operator-DM routing, ex-patch 0010) plus
operator-only command gating. The cron mechanisms stay in the tree: the denylist is
inert unless `cron.disabled_toolsets` is set, and script-backed jobs are still refused from chat.

Text-level so the tier stays hermetic. The dashboard Help page's Security section is the
reference.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG = REPO_ROOT / "luna" / "config" / "config.yaml.luna"


def _list_items(text: str, header: str) -> list[str]:
    """Items of the ``<header>:`` block (2-space key, 4-space ``- item`` run)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line == header)
    items = []
    for line in lines[start + 1:]:
        if line.startswith("    - "):
            items.append(line[6:].strip())
        elif line.strip() and not line.startswith("  #"):
            break
    return items


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_telegram_keeps_the_execution_toolsets():
    items = _list_items(CONFIG.read_text(encoding="utf-8"), "  telegram:")
    assert items, "telegram toolset list missing"
    assert {"terminal", "file", "code_execution"} <= set(items)
    assert "cronjob" in items  # reminders keep working


def test_admin_gating_is_configured():
    text = CONFIG.read_text(encoding="utf-8")
    # Omitting an admin list disables command gating for that scope, so both must be present.
    assert "allow_admin_from:" in text
    assert "group_allow_admin_from:" in text
    assert "user_allowed_commands:" in text
    assert "group_user_allowed_commands:" in text


def test_cron_denylist_mechanism_is_available_but_unset():
    # `cron.disabled_toolsets` layers last so a per-job enabled_toolsets cannot widen an
    # unattended run; the operator currently leaves it unset (full tools).
    assert 'cron_cfg.get("disabled_toolsets")' in _read("cron/scheduler.py")
    assert "disabled_toolsets:" not in CONFIG.read_text(encoding="utf-8")


def test_script_backed_cron_is_denied_from_chat():
    # A script/no_agent job runs shell in the scheduler with no agent, so no toolset gates it; it is
    # refused at create/update/run whenever the call carries a chat origin.
    tools = _read("tools/cronjob_tools.py")
    assert "_chat_surface_script_denied" in tools
    assert tools.count("_chat_surface_script_denied(") >= 4  # definition + create + run + update
    assert "_origin_from_env" in tools
