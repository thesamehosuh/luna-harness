"""Explicit, owner-approved disclosure of a bounded private file-memory excerpt."""
from __future__ import annotations

import html
import json
import re
import uuid

from luna_core import config_read
from luna_core.group_memory import owner_dm, transport_context
from luna_core.runtime import home
from luna_core.surface_policy import room_surface


def _excerpt(path, query):
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Private memory must be a regular profile-owned file")
    if not path.exists():
        return ""
    if path.stat().st_size > 256_000:
        raise ValueError("Private memory is too large to share through this tool")
    text = path.read_text()
    entries = [entry.strip() for entry in text.split("\n§\n") if entry.strip()]
    tokens = set(re.findall(r"\w{2,}", query.lower()))
    if tokens:
        ranked = sorted(enumerate(entries), key=lambda item: (
            -sum(token in item[1].lower() for token in tokens), item[0]))
        entries = [entry for _, entry in ranked if any(token in entry.lower() for token in tokens)]
    text = "\n§\n".join(entries)
    # The EXACT excerpt must fit unabridged inside Telegram's escaped approval
    # card, including pathological HTML characters and non-BMP code points.
    while len(html.escape(text).encode("utf-16-le")) // 2 > 1800:
        text = text[:max(0, int(len(text) * 0.85))]
    return text


def tool_handler(args, **kwargs):
    try:
        ctx, config = transport_context(), config_read.load_config()
        source = args.get("source")
        if source not in {"user", "memory"}:
            raise ValueError("Choose user or memory")
        query = args.get("query") or ""
        if not isinstance(query, str) or len(query) > 300:
            raise ValueError("Use a short memory lookup query")
        local = ctx["platform"] in {"cli", "tui", "desktop", "local"}
        direct = local or owner_dm(config, ctx["platform"], ctx["chat_type"], ctx["chat_id"], ctx["user_id"])
        group = room_surface(ctx["chat_type"])
        if not direct and (not group or ctx["platform"] != "telegram"):
            raise ValueError("Private files are available to the owner, or to Telegram groups after owner-DM approval")
        from tools.skill_provenance import is_unattended_review
        from agent.delegation_context import is_delegated_child_context
        if is_unattended_review() or is_delegated_child_context():
            raise ValueError("Private-memory disclosure requires an active foreground conversation")
        filename = "USER.md" if source == "user" else "MEMORY.md"
        text = _excerpt(home() / "memories" / filename, query)
        if direct:
            return json.dumps({"file": filename, "content": text}, ensure_ascii=False)
        from gateway.run import _redact_approval_command
        text = _redact_approval_command(text)
        from gateway.session_context import get_session_env
        from tools.approval_context import get_current_session_key
        from tools import approval
        from tools.approval_gateway_wait import _await_gateway_decision
        from tools.interrupt import is_interrupted
        original_key = get_current_session_key()
        message_id = str(get_session_env("HERMES_SESSION_MESSAGE_ID", "") or "")
        if not original_key or not message_id:
            raise ValueError("This request has no active transport conversation")
        with approval._lock:
            notify = approval._gateway_notify_cbs.get(original_key)
        if notify is None:
            raise ValueError("Owner-DM approval is unavailable; no private content was shared")
        # A group /approve resolves its own queue, NEVER this unguessable owner-DM
        # queue. Buttons and the owner's forwarded /approve resolve only this read.
        key = "private-memory:" + uuid.uuid4().hex
        preview = (f"Share {filename} with group {ctx['chat_id']}"
                   + (f", topic {ctx['thread_id']}" if ctx["thread_id"] else "")
                   + f", message {message_id}\nExact excerpt:\n{text or '[No matching entries]'}")
        decision = _await_gateway_decision(key, notify, {
            "command": preview,
            "description": "Approve sharing this exact private excerpt with the model answering the group. "
                           "It may remain in that group's conversation and saved memory. This grants one read only.",
            "pattern_key": "private_memory_disclosure", "pattern_keys": ["private_memory_disclosure"],
            "allow_permanent": False, "allow_session": False, "owner_dm_only": True,
            "preview_sanitized": True,
            "approval_session_key": key,
        })
        if not decision.get("resolved") or decision.get("choice") != "once" or decision.get("cancelled") or is_interrupted():
            return json.dumps({"ok": False, "message": "Private memory was not shared: owner approval was denied, unavailable, withdrawn or expired."})
        from luna_core.room_dispatch import current_target
        target = current_target()
        if target is not None and (target.cancelled.is_set() or target.clock() > target.deadline):
            return json.dumps({"ok": False, "message": "The group request expired; private memory was not shared."})
        # Return the approved snapshot, even if the source file changed while the
        # owner was deciding. Approval can never unlock a different later value.
        return json.dumps({"file": filename, "content": text, "owner_approved": True,
                           "destination": {"chat_id": ctx["chat_id"], "thread_id": ctx["thread_id"]}}, ensure_ascii=False)
    except (ValueError, OSError) as exc:
        return json.dumps({"ok": False, "error": str(exc)})


TOOL_SCHEMA = {"name": "private_memory", "description": "Look up an excerpt from the owner's private USER.md or MEMORY.md. In a Telegram group this ALWAYS requires an explicit one-read approval sent privately to the owner, showing the exact excerpt and destination group. No private content reaches the group model before approval. Owner DMs may read directly. Background reviews cannot use this tool. This tool never writes files.",
    "parameters": {"type": "object", "properties": {
        "source": {"type": "string", "enum": ["user", "memory"]},
        "query": {"type": "string", "description": "Short literal keywords to select relevant memory entries; empty selects a bounded file excerpt."}},
        "required": ["source", "query"], "additionalProperties": False}}
