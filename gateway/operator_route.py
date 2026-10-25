"""Operator-DM routing for non-conversational gateway output (Luna patch 0010).

A hermes turn produces two kinds of outbound traffic:

* the **conversational reply** (the agent's answer), which belongs in the chat the user spoke in;
* **non-conversational output** — status/diagnostic warnings, operational notices, and interactive
  approval/clarify prompts.

On a group surface the second kind is noise and leaks operator context. When a turn runs on a
group/channel surface and ``luna.notify.operator_chat.<platform>`` names an operator DM, that output
is delivered to the operator DM instead; the conversational reply still goes to the group.

This module is the single decision point:

* :func:`operator_status_target` — chat id to use for the turn's status/prompt surface (consumed in
  ``gateway/run_turn.py`` when the turn wiring is bound).
* :func:`operator_notice_target` — chat id for direct operational notices (consumed in
  ``gateway/run_notifications.py::_deliver_platform_notice``).
* :func:`register_forwarded_prompt` / :func:`resolve_forwarded_session_key` — correlation so a
  typed reply in the operator DM satisfies the pending gate of the group turn. (Button taps already
  correlate through their callback payload; this covers typed ``/approve``, ``/deny`` and clarify
  answers, which would otherwise key on the operator DM's own session.)

Cron is exempt. The cron scheduler runs its own agent session and delivers through
``cron/scheduler_delivery.py`` with its own policy (``deliver=origin|in_channel|target`` plus its own
origin-DM mirroring); nothing there routes through this module, and the ``origin="cron"`` guard below
keeps it that way for any caller that might.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

# Chat types that count as a "group surface": output here goes to the operator instead.
GROUP_CHAT_TYPES = frozenset({"group", "supergroup", "channel", "forum"})

# Values that mean "operator DM not configured" (the config template ships the placeholder '0').
_DISABLED_CHAT_IDS = frozenset({"", "0", "none", "null", "false", "off"})

# How long a forwarded-prompt correlation stays valid. Gates themselves time out far sooner.
_PROMPT_TTL_SECONDS = 3600.0

_prompt_lock = threading.Lock()
# chat key ("<platform>:<operator chat id>") -> [(session_key, created_at)], oldest first.
_prompt_routes: "dict[str, list[tuple[str, float]]]" = {}


def platform_key(platform) -> str:
    """Lower-cased platform key used for config lookups and chat keys."""
    return str(getattr(platform, "value", platform) or "").strip().lower()


def is_group_surface(source) -> bool:
    """True when this source is a group/channel/forum surface (not a DM)."""
    return str(getattr(source, "chat_type", "") or "").strip().lower() in GROUP_CHAT_TYPES


def normalize_chat_id(raw) -> "str | None":
    """Return a usable chat id, or ``None`` for placeholder/disabled values."""
    text = str(raw).strip() if raw is not None else ""
    if text.lower() in _DISABLED_CHAT_IDS:
        return None
    return text or None


def _config_get(config, *keys, default=None):
    """Tiny nested lookup so this module needs no config loader (and stays importable standalone)."""
    node = config
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def operator_chat_id(user_config, platform) -> "str | None":
    """Operator DM chat id from ``luna.notify.operator_chat.<platform>``; ``None`` when unset."""
    return normalize_chat_id(
        _config_get(user_config, "luna", "notify", "operator_chat", platform_key(platform))
    )


def _load_user_config(user_config):
    if isinstance(user_config, dict):
        return user_config
    try:
        from gateway.warning_notifications import effective_user_config
        return effective_user_config()
    except Exception:
        logger.debug("operator routing: user config unavailable", exc_info=True)
        return None


def _operator_target(source, *, user_config=None, origin="gateway") -> "str | None":
    if origin == "cron" or not is_group_surface(source):
        return None
    target = operator_chat_id(_load_user_config(user_config), getattr(source, "platform", None))
    if target is None or target == str(getattr(source, "chat_id", "") or ""):
        return None
    return target


def operator_status_target(source, *, user_config=None, origin="gateway") -> "str | None":
    """Operator DM chat id for a group turn's status/notice/prompt surface; ``None`` = leave as-is."""
    return _operator_target(source, user_config=user_config, origin=origin)


def operator_notice_target(source, *, user_config=None, origin="gateway") -> "str | None":
    """Operator DM chat id for a direct operational notice; ``None`` = deliver as usual."""
    return _operator_target(source, user_config=user_config, origin=origin)


def _chat_key(platform, chat_id) -> str:
    return f"{platform_key(platform)}:{chat_id}"


def register_forwarded_prompt(source, session_key: str, *, target_chat_id=None) -> None:
    """Remember that ``session_key``'s prompt was delivered to ``target_chat_id``.

    No-op when the prompt was not routed away from the source chat (routing disabled, or a DM turn),
    so a deployment without an operator DM keeps today's behaviour exactly.
    """
    session_key = str(session_key or "").strip()
    origin_chat = str(getattr(source, "chat_id", "") or "").strip()
    target = str(target_chat_id or origin_chat).strip()
    if not session_key or not target or target == origin_chat:
        return
    key = _chat_key(getattr(source, "platform", None), target)
    now = time.time()
    with _prompt_lock:
        entries = [e for e in _prompt_routes.get(key, ()) if now - e[1] < _PROMPT_TTL_SECONDS]
        entries = [e for e in entries if e[0] != session_key]
        entries.append((session_key, now))
        _prompt_routes[key] = entries


def resolve_forwarded_session_key(source, *, still_pending) -> "str | None":
    """Oldest forwarded prompt for the chat this reply arrived in whose gate is still open.

    ``still_pending(session_key) -> bool`` reports whether that session still has a pending gate.
    Entries whose gate has resolved (or that aged out) are pruned here, so a stale registration can
    never capture an unrelated reply.
    """
    key = _chat_key(getattr(source, "platform", None), str(getattr(source, "chat_id", "") or ""))
    now = time.time()
    found = None
    with _prompt_lock:
        live = []
        for session_key, created in _prompt_routes.get(key, ()):
            if now - created >= _PROMPT_TTL_SECONDS:
                continue
            try:
                pending = bool(still_pending(session_key))
            except Exception:
                logger.debug("forwarded-prompt liveness check failed", exc_info=True)
                pending = False
            if not pending:
                continue
            live.append((session_key, created))
            if found is None:
                found = session_key
        if live:
            _prompt_routes[key] = live
        else:
            _prompt_routes.pop(key, None)
    return found
