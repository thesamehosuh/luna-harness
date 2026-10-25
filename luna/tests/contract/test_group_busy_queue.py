"""Contract: group surfaces queue follow-ups instead of steering/interrupting (ex-patch 0014).

Text-level so the tier stays hermetic; the runtime behaviour is exercised in review against the
hermes venv (``gateway/run_config_loaders.py::_surface_busy_override``).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG = REPO_ROOT / "luna" / "config" / "config.yaml.luna"


def _block(text: str, header: str) -> str:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line == header)
    out = []
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith("      ") and not line.startswith("    #"):
            break
        out.append(line)
    return "\n".join(out)


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_group_surface_queues_followups():
    block = _block(CONFIG.read_text(encoding="utf-8"), "    telegram_group:")
    assert "busy_input_mode: queue" in block


def test_dm_keeps_the_global_busy_default():
    text = CONFIG.read_text(encoding="utf-8")
    # Exactly one surface sets it, so the DM inherits the runner default (interrupt).
    assert text.count("busy_input_mode:") == 1


def test_busy_mode_is_surface_aware():
    loaders = _read("gateway/run_config_loaders.py")
    assert "_surface_busy_override" in loaders
    assert "_surface_config_key" in loaders
    assert "busy_input_mode" in loaders and "busy_text_mode" in loaders
    # DMs/profiles are preserved: the override only wins when the surface sets a valid value.
    assert "if value in _BUSY_INPUT_MODES else" in loaders


def test_queued_final_reply_is_anchored_to_the_queued_message():
    # The chain's terminal response used to be posted as a reply to the message that OPENED the
    # chain; it is now anchored to the queued message instead.
    base = _read("gateway/platforms/base.py")
    assert "_queued_terminal_reply_anchor" in base
    assert "queued_terminal_inbound_id" in base
    # The gateway handler returns text, so it must stash the id on the event for base.py to read.
    turn = _read("gateway/run_turn.py")
    assert "_luna_queued_reply_anchor" in turn
