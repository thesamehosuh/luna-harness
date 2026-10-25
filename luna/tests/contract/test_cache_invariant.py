"""Prompt-cache contract: per-turn dynamic content must never perturb the cached-agent signature.

The plan's T0 invariant (``test_agent_config_signature_stable``): the sidecar notes carry the room
block, reply chains, and recall — none of which may enter ``_agent_config_signature`` (or the
system prompt). If upstream folds them in, every group turn rebuilds the agent and the prompt
cache dies; the cost regression is silent. These are source-level checks (the gateway modules
import heavy deps unavailable in the light test venv), so they fail the moment an upstream merge
reshapes the boundary. A failure BLOCKS the merge (AGENTS.md §6/§7).
"""

from __future__ import annotations

import re

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.is_file(), f"missing upstream file: {rel}"
    return path.read_text(encoding="utf-8", errors="replace")


def _function_body(source: str, name: str) -> str:
    """Source text of ``def name(...)`` up to the next statement at the same indent (or less)."""
    match = re.search(rf"^([ \t]*)def {re.escape(name)}\(", source, re.MULTILINE)
    assert match, f"{name} not found"
    indent = len(match.group(1))
    started = False
    body_lines = []
    for line in source[match.start():].splitlines():
        if not started:
            if line.rstrip().endswith(":"):
                started = True
            continue
        stripped = line.strip()
        if stripped:
            line_indent = len(line) - len(line.lstrip())
            if line_indent <= indent and not line.lstrip().startswith(("#", '"""', "'''")):
                break
        body_lines.append(line)
    return "\n".join(body_lines)


def test_consume_sidecar_symbol_exists():
    """luna-room's append-staging wrapper composes set+consume; both must exist upstream.

    (The luna-room docstring claims this is contract-tested — this is that test.)
    """
    cache = _read("gateway/run_agent_cache.py")
    assert "_consume_pending_turn_sidecar_notes" in cache, (
        "_consume_pending_turn_sidecar_notes was renamed/removed — luna-room's append-staging "
        "wrapper falls back to a replacing setter and the room block is dropped on first turns."
    )
    assert "_set_pending_turn_sidecar_notes" in cache


def test_sidecar_notes_do_not_enter_the_agent_config_signature():
    """The cache invariant itself: notes are per-turn state, never signature inputs."""
    cache = _read("gateway/run_agent_cache.py")
    body = _function_body(cache, "_agent_config_signature")
    for forbidden in ("sidecar", "note", "room", "recall"):
        assert forbidden not in body.lower(), (
            f"'{forbidden}' appears inside _agent_config_signature — per-turn content perturbs "
            "the cached-agent key and every group turn rebuilds the agent (prompt cache dies)."
        )


def test_sidecar_notes_ride_the_user_message_not_the_system_prompt():
    """Notes must be delivered on the user message (ephemeral api_content), not in the prompt.

    The delivery chain: run_turn_runner consumes the staged notes onto the agent, and
    agent/turn_context._merge_gateway_notes folds them into the current user message — the
    ephemeral system prompt must stay byte-stable across turns (that is the cache).
    """
    runner = _read("gateway/run_turn_runner.py")
    assert "_consume_pending_turn_sidecar_notes" in runner, (
        "run_turn_runner.py no longer consumes the staged sidecar notes"
    )
    turn_ctx = _read("agent/turn_context.py")
    body = _function_body(turn_ctx, "_merge_gateway_notes")
    assert "consume_gateway_turn_context_notes" in body, (
        "_merge_gateway_notes no longer folds the gateway notes into the user message"
    )
    for prompt_word in ("system_prompt", "build_system", "ephemeral_prompt"):
        assert prompt_word not in body, (
            f"_merge_gateway_notes touches {prompt_word} — per-turn notes must never reach the "
            "system prompt (prompt-cache invariant)."
        )


def test_sync_turn_receives_the_raw_user_message_only():
    """Indexed context must not double-persist: sync_turn carries raw turn content, and the
    injected room/recall block is staged separately (sidecar) and never written back."""
    memory = _read("luna/plugins/luna-memory/__init__.py")
    assert "def sync_turn" in memory
    body = _function_body(memory, "sync_turn")
    # The room block is luna-room's product; the memory write path must not compose or persist it.
    assert "build_room_block" not in body and "sidecar" not in body.lower(), (
        "sync_turn now touches the room/sidecar path — injected context would double-persist "
        "into Honcho (and would put group chatter in per-user memory)."
    )


def test_overlay_never_writes_channel_prompt():
    """No overlay plugin may assign to ``channel_prompt``.

    ``channel_prompt`` is system-level and enters the cached-agent signature (AGENTS.md §3
    invariant 1). ``luna-room`` used to concatenate untrusted group chatter into it whenever the
    private sidecar seam was unavailable — an exception in the safe path promoting attacker text
    into the highest-trust slot.

    Detected via the AST rather than a text scan: the module's own docstring and its warning log
    both *mention* channel_prompt, and a grep-based check cannot tell a write from a mention.
    """
    import ast

    plugins = REPO_ROOT / "luna" / "plugins"
    offenders = []

    def _is_channel_prompt(node: ast.AST) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "channel_prompt"

    for path in sorted(plugins.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[ast.AST] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            if any(_is_channel_prompt(t) for t in targets):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: attribute assignment")
            # setattr(event, "channel_prompt", ...) is the same write by another name.
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "setattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "channel_prompt"
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: setattr")

    assert not offenders, (
        "overlay plugin writes channel_prompt (system-level, cached signature):\n"
        + "\n".join(offenders)
    )
