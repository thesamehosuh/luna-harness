"""Dashboard schema contributions for the companion knobs.

The engine generates its config schema from ``DEFAULT_CONFIG`` only, which leaves every ``luna.*``
key as raw YAML (PRODUCT_PLAN §4: "a key that only exists in raw YAML is not done"). This module
contributes form fields for the ``luna`` overlay config, the ``honcho`` client block, and the
``display.platforms.telegram_group`` surface — merged into the engine's ``CONFIG_SCHEMA`` by
``hermes_cli/web_server_config.py``.

Threshold fields are generated from ``luna_core.cascade.CascadeConfig`` so the form cannot drift
from the code defaults; explicit ``_RANGES`` give the UI validation bounds.
"""

from __future__ import annotations

from typing import Any, Dict

CATEGORY = "companion"

# ── Field builders ───────────────────────────────────────────────────────────────────────────────


def _field(kind: str, description: str, **extra: Any) -> Dict[str, Any]:
    return {"type": kind, "description": description, "category": CATEGORY, **extra}


def _num(description: str, *, minimum: float | None = None, maximum: float | None = None,
         step: float | None = None, **extra: Any) -> Dict[str, Any]:
    out = _field("number", description, **extra)
    if minimum is not None:
        out["min"] = minimum
    if maximum is not None:
        out["max"] = maximum
    if step is not None:
        out["step"] = step
    return out


def _bool(description: str, **extra: Any) -> Dict[str, Any]:
    return _field("boolean", description, **extra)


def _text(description: str, **extra: Any) -> Dict[str, Any]:
    return _field("string", description, **extra)


def _select(description: str, *options: str, **extra: Any) -> Dict[str, Any]:
    return _field("select", description, options=list(options), **extra)


def _list(description: str, **extra: Any) -> Dict[str, Any]:
    return _field("list", description, **extra)


# ── Cascade thresholds (generated from CascadeConfig) ────────────────────────────────────────────

# Validation bounds per threshold: (min, max). Floats stay in [0, 1] unless noted.
_RANGES: Dict[str, tuple[float, float]] = {
    "min_new_messages": (1, 1000),
    "min_minutes_since_luna": (0, 1440),
    "min_candidate_chars": (1, 500),
    "state_max_chars": (500, 100000),
    "recent_lines": (1, 500),
    "timeliness_center": (0, 5),
    "timeliness_band": (0, 5),
}

# Floats that are semantically whole numbers. `min_minutes_since_luna` is typed float only because
# the cascade does arithmetic on it; a control stepping it by 0.01 minutes is noise, and the
# generated schema entry needs the same step so the config form and the slider agree.
_WHOLE_NUMBER_STEPS: Dict[str, float] = {
    "min_minutes_since_luna": 1,
}

_THRESHOLD_DOCS: Dict[str, str] = {
    "min_new_messages": "Minimum new room messages before a wake is considered (rarity gate).",
    "min_minutes_since_luna": "Minutes since the companion last spoke before another self-wake.",
    "min_candidate_chars": "Minimum candidate message length (skips one-word noise).",
    "directed_min_addressed": "Addressed-score above which a message counts as aimed at the companion.",
    "message_min_value": "Minimum value score for a text self-wake (calibrated on replay).",
    "message_min_fit": "Minimum fit score: would speaking up be welcome here?",
    "reaction_yield_open_question": "A candidate scoring above this on open-question yields to a text reply instead of a reaction.",
    "reaction_yield_add_value": "A candidate scoring above this on add-value yields to a text reply.",
    "timeliness_center": "Centre of the 'just right' timing band (middle score level).",
    "timeliness_band": "Half-width of the just-right timing band.",
    "message_max_addressed": "Above this addressed score a message is a direct ask and never an ambient wake.",
    "message_max_sensitive": "Sensitive-topic ceiling for text wakes (a sensitive message never wakes).",
    "message_max_private": "Privacy ceiling for text wakes.",
    "message_max_venting": "Venting ceiling for text wakes.",
    "safety_max_sensitive": "Hard safety ceiling on sensitive topics (all tiers).",
    "safety_max_private": "Hard safety ceiling on private topics (all tiers).",
    "reaction_min_fit": "Minimum fit for the reaction tier.",
    "reaction_min_value": "Minimum value for the reaction tier (deliberately low; value is written for text).",
    "reaction_min_freshness": "Minimum freshness for the reaction tier (anti-bunching).",
    "reaction_min_emoji_confidence": "Minimum emoji_choice confidence for a reaction.",
    "reaction_max_open_question": "Above this open-question score a reaction yields to a real answer.",
    "reaction_request_min": "Score above which an explicit 'react to this' request fires.",
    "reaction_max_sensitive": "Sensitive-topic ceiling for reactions (a rant is fine; distress is not).",
    "state_max_chars": "Character ceiling of the cascade state block.",
    "recent_lines": "Recent context lines considered per candidate.",
}


def _threshold_fields() -> Dict[str, Dict[str, Any]]:
    try:
        from luna_core.cascade import CascadeConfig
        import dataclasses
    except Exception:  # pragma: no cover - schema must survive a missing overlay lib
        return {}
    fields: Dict[str, Dict[str, Any]] = {}
    for f in dataclasses.fields(CascadeConfig):
        default = CascadeConfig().__dict__.get(f.name)
        low_high = _RANGES.get(f.name)
        if low_high is None:
            low_high = (0.0, 1.0) if isinstance(default, float) else (0, 10 ** 6)
        description = _THRESHOLD_DOCS.get(f.name, f.name.replace("_", " ").capitalize() + ".")
        if isinstance(default, int) and not isinstance(default, bool):
            entry = _num(description, minimum=low_high[0], maximum=low_high[1], step=1)
            entry["type"] = "number"
            entry["default"] = default
        else:
            step = _WHOLE_NUMBER_STEPS.get(f.name)
            entry = _num(description, minimum=low_high[0], maximum=low_high[1], step=step)
            entry["default"] = default
        fields[f"luna.ambient.thresholds.{f.name}"] = entry
    return fields


def threshold_bounds() -> Dict[str, Dict[str, Any]]:
    """Per-threshold validation bounds, keyed by bare cascade field name.

    Same source of truth as the generated ``luna.ambient.thresholds.*`` schema entries, but keyed
    the way ``/api/luna/thresholds`` keys them (``min_new_messages``, not the dotted config path).
    The Behaviour page needs these because a slider cannot infer its own range: rendering every
    threshold against a hardcoded ``max=1`` pins a minutes-since-last-spoke value of 10 to the far
    right and makes dragging left write 0. Empty dict when the overlay lib is unavailable, so a
    caller must degrade rather than assume a range.
    """
    bounds: Dict[str, Dict[str, Any]] = {}
    for dotted, entry in _threshold_fields().items():
        name = dotted.rsplit(".", 1)[-1]
        bounds[name] = {
            "min": entry.get("min"),
            "max": entry.get("max"),
            "step": entry.get("step"),
            "description": entry.get("description"),
        }
    return bounds


# ── Static companion fields ──────────────────────────────────────────────────────────────────────

_STATIC: Dict[str, Dict[str, Any]] = {
    "luna.setup.memory": _select("Optional memory setup choice.", "pending", "enabled", "skipped"),
    "luna.setup.jev": _select("Optional self-wake setup choice.", "pending", "enabled", "skipped"),
    "luna.setup.telegram": _select("Optional Telegram setup choice; dashboard chat works independently.", "pending", "enabled", "skipped"),
    "luna.opencode.timeout_seconds": _num("Maximum wait for a native OpenCode reply.", minimum=30, maximum=1800, step=1),
    "luna.memory_stack.reasoning_source": _select("Use the companion's current connection or an explicit memory model.", "companion", "custom"),
    "luna.memory_stack.reasoning_effort": _select("Memory reasoning effort, independent of the companion. Native OpenCode currently supports provider default only.", "default", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"),
    "luna.memory_stack.docker_context": _text("Advanced: a local Docker context for this installation. Empty reuses the current local engine or Luna's recorded Desktop context."),
    "luna.memory_stack.provider": _text("Configured provider for an explicit memory reasoning model."),
    "luna.memory_stack.embedding_source": _select("Bundled CPU embeddings, or an advanced existing endpoint. Changing a populated index requires migration.", "bundled", "custom"),
    "luna.memory_stack.base_url": _text("OpenAI-compatible endpoint for the local memory stack's reasoning model."),
    "luna.memory_stack.model": _text("Reasoning model used to extract and recall memories."),
    "luna.memory_stack.api_key_env": _text("Secret variable containing the memory provider API key."),
    "luna.memory_stack.embedding_base_url": _text("OpenAI-compatible endpoint serving embeddings."),
    "luna.memory_stack.embedding_model": _text("Embedding model served by the memory endpoint."),
    "luna.memory_stack.embedding_key_env": _text("Embedding API key variable; defaults to the memory provider key."),
    "luna.memory_stack.embedding_dimensions": _num("Embedding vector dimensions; choose before creating the memory database.", minimum=1, maximum=65536, step=1),
    # Identity
    "luna.docs.url": _text(
        "Documentation URL for the dashboard's Docs page. Empty = link to the in-dashboard /help.",
    ),
    "luna.telegram.onboarding_service_url": _text(
        "Quick-setup service for the 'Create with QR' Telegram panel. Empty = off, and manual "
        "bot-token entry is the only path. A third party creates your bot and learns your user id, "
        "so this is opt-in.",
    ),
    "luna.identity.platform": _select(
        "Transport platform the identity registry keys on", "telegram", "discord", "slack",
    ),
    "luna.identity.peer_prefix": _text("Prefix for generated peer ids (e.g. telegram_1001)."),
    "luna.identity.overrides_file": _text(
        "Manual identity override file ($HERMES_HOME/identity_overrides.json).",
    ),
    # Telegram surface: who may talk, who may approve, and what she reacts to. Every key the
    # template ships is a first-class dashboard field (AGENTS.md §6: raw-YAML-only is not done).
    "telegram.reactions": _bool(
        "Enable the adapter's reaction capability (required for the companion's self-wake reactions).",
    ),
    "telegram.progress_reactions": _bool(
        "Show lifecycle reactions on ordinary messages. Off keeps the companion quiet.",
    ),
    "telegram.extra.rich_messages": _bool("Send rich formatted messages."),
    "telegram.extra.rich_drafts": _bool("Send rich streaming drafts."),
    "telegram.allow_from": _list(
        "Telegram ids allowed to DM the companion and to approve actions in a DM. '*' allows everyone.",
    ),
    "telegram.group_allow_from": _list(
        "Telegram ids allowed to act in a group AND to approve actions there. '*' allows everyone.",
    ),
    "telegram.allow_admin_from": _list(
        "Telegram ids that get every slash command, in DMs. Leave empty and command gating is off.",
    ),
    "telegram.group_allow_admin_from": _list(
        "Telegram ids that get every slash command, in groups.",
    ),
    "telegram.require_mention": _bool(
        "Only act on an explicit @-mention in groups. Off means every group message is addressed to the companion.",
    ),
    "telegram.group_allowed_chats": _list(
        "Group chat ids the companion may work in. This admits the whole chat, so it is NOT an approver list.",
    ),
    "telegram.user_allowed_commands": _list("Slash commands any allowed DM user may run."),
    "telegram.group_user_allowed_commands": _list(
        "Slash commands any allowed group member may run.",
    ),
    # Room block (cache-safe sidecar budget)
    "telegram.observe_unmentioned_group_messages": _bool(
        "Record unmentioned group messages into the room log. The companion reads the room to judge when "
        "to speak; this is the widest thing the product stores, and the retention window in "
        "luna.data.retention_days is what bounds it. Off means the companion only sees messages addressed "
        "to it, and loses the ability to chime in unprompted.",
    ),
    "luna.room.chat_id": _text(
        "Group chat id whose room block is staged each turn (blank = telegram.group_allowed_chats single entry).",
    ),
    "luna.room.max_lines": _num("Room lines staged per turn.", minimum=1, maximum=200, step=1),
    "luna.room.max_chars": _num("Character budget of the room block.", minimum=100, maximum=20000, step=1),
    "luna.room.max_age_minutes": _num("Drop room lines older than this.", minimum=1, maximum=10080, step=1),
    "luna.room.per_line_chars": _num("Per-line truncation of the room block.", minimum=40, maximum=2000, step=1),
    "luna.room.thread_depth": _num("Reply-chain depth reconstructed per turn.", minimum=0, maximum=50, step=1),
    # Output policy (group shaping)
    "luna.output.emoji_filter": _bool("Enforce the group emoji policy in code as well as in the persona."),
    "luna.output.strip_emoji": _bool(
        "Strip every emoji. Honoured even when emoji_filter is off."
    ),
    "luna.output.allowed_emoji": _list("Emoji that survive the filter (earned by the persona)."),
    "luna.output.max_lines": _num(
        "Hard line cap for group replies.", minimum=1, maximum=50, step=1,
    ),
    # Memory ceilings
    "luna.memory.recall_max_chars": _num(
        "Hard recall character ceiling (the prefetch regression guard).", minimum=100, maximum=100000, step=1,
    ),
    "luna.memory.prefetch_max_chars": _num(
        "Prefetch character ceiling per turn.", minimum=100, maximum=100000, step=1,
    ),
    "luna.memory.room_session_scope": _select(
        "Scope of the shared Honcho room session", "room", "session",
    ),
    "luna.memory.shared_room_session": _bool("Share one Honcho room session for the whole group."),
    # Data / logs
    "luna.data.retention_days": _num("Days of indexed messages to keep.", minimum=0, maximum=3650, step=1),
    "luna.data.batch_size": _num("Indexer batch size.", minimum=1, maximum=10000, step=1),
    "luna.data.prune_gateway_state": _bool(
        "Also prune the gateway's observed rows in state.db. Needs an indexer watermark; without "
        "one nothing is pruned there, so un-indexed history is never at risk."
    ),
    "luna.data.auto_prune": _bool(
        "Enforce the retention window automatically from the gateway (recommended on). Gates only "
        "the automatic passes: a manual prune, and the daily retention timer, still run.",
    ),
    "luna.data.auto_prune_interval_minutes": _num(
        "Minutes between automatic retention passes.", minimum=1, maximum=10080, step=1,
    ),
    "luna.logs.retention_days": _num("Days of log files to keep.", minimum=0, maximum=3650, step=1),
    "luna.logs.files": _list("Log files covered by retention."),
    # Ambient (wake behaviour)
    "luna.ambient.watched_chats": _list("Opt-in allowed Telegram groups to watch; empty watches none and new groups remain opted out."),
    "luna.ambient.enabled": _bool("Master switch for the self-wake cascade."),
    "luna.ambient.dry_run": _bool(
        "Dry-run: decide but never send (flip to false only after reviewing the verdict feed).",
    ),
    "luna.ambient.room_register": _text(
        "How the room talks. Shapes the companion's wake judgments separately from the persona.",
    ),
    "luna.ambient.settle_seconds": _num(
        "Let a message settle this long before spending a judgment (0 = ask about every message).",
        minimum=0, maximum=600, step=1,
    ),
    "luna.ambient.poll_seconds": _num(
        "Wake poll cadence (dominant reply-latency term).", minimum=1, maximum=300, step=1,
    ),
    "luna.ambient.stale_after_minutes": _num(
        "Skip a backlog older than this (fast-forward instead of spending judgments).",
        minimum=1, maximum=1440, step=1,
    ),
    # jev route chain
    "luna.ambient.jev.timeout_seconds": _num(
        "Total Jev judgment deadline across routes and retries.", minimum=1, maximum=60, step=1,
    ),
    "luna.ambient.jev.route": _list(
        "Ordered provider route chain (names from luna.ambient.jev.providers; first is primary).",
    ),
    # Budget / cooldowns
    "luna.ambient.budget.message_cooldown_minutes": _num(
        "Minimum minutes between ambient text wakes (0 = rely on jev).", minimum=0, maximum=1440, step=1,
    ),
    "luna.ambient.budget.message_max_per_day": _num(
        "Hard daily text-wake ceiling (loop protection).", minimum=0, maximum=10 ** 6, step=1,
    ),
    "luna.ambient.budget.message_max_per_week": _num(
        "Hard weekly text-wake ceiling.", minimum=0, maximum=10 ** 6, step=1,
    ),
    "luna.ambient.budget.reaction_cooldown_minutes": _num(
        "Minimum minutes between reactions (keeps reactions from bunching).", minimum=0, maximum=1440, step=1,
    ),
    "luna.ambient.budget.reaction_max_per_day": _num(
        "Hard daily reaction ceiling.", minimum=0, maximum=10 ** 6, step=1,
    ),
    "luna.ambient.budget.reaction_max_per_week": _num(
        "Hard weekly reaction ceiling.", minimum=0, maximum=10 ** 6, step=1,
    ),
    "luna.ambient.budget.directed_cooldown_minutes": _num(
        "Minimum minutes between directed-reply wakes.", minimum=0, maximum=1440, step=1,
    ),
    "luna.ambient.budget.directed_max_per_day": _num(
        "Hard daily directed-wake ceiling.", minimum=0, maximum=10 ** 6, step=1,
    ),
    "luna.ambient.budget.directed_max_per_week": _num(
        "Hard weekly directed-wake ceiling.", minimum=0, maximum=10 ** 6, step=1,
    ),
    "luna.ambient.mention_fallback": _list(
        "Regexes that wake the companion when Jev is down (outage path only; empty = stay silent).",
    ),
    "luna.ambient.reactions.allowed": _list(
        "Allowed reaction emoji (empty list disables the reaction tier).",
    ),
    # Operator routing
    "luna.notify.operator_chat.telegram": _text(
        "Operator DM chat id for non-conversational group output ('0'/empty disables routing).",
    ),
    # Logger (indexer)
    "luna.logger.state_db": _text("Gateway state.db the indexer tails."),
    "luna.logger.index_db": _text("Derived index database (luna-state.db)."),
    "luna.logger.poll_seconds": _num("Index poll cadence.", minimum=1, maximum=300, step=1),
    "luna.logger.batch": _num("Rows indexed per batch.", minimum=1, maximum=10000, step=1),
    "luna.logger.sync_honcho": _bool("Keep the Honcho room session current (best-effort)."),
}

# ── Honcho client block (curated panel; the memory provider behind luna-memory) ───────────────────

_HONCHO: Dict[str, Dict[str, Any]] = {
    "honcho.baseUrl": _text("Honcho API base URL.", category="memory"),
    "honcho.contextTokens": _num(
        "Token ceiling for recalled context; 0 leaves the Honcho client uncapped. Luna's output recall limit still applies.", minimum=0, maximum=100000, step=1, category="memory",
    ),
    "honcho.dialecticCadence": _num(
        "Turns between dialectic reasoning calls. Higher values make fewer model calls.", minimum=1, maximum=100, step=1, category="memory",
    ),
    "honcho.dialecticMaxChars": _num(
        "Character ceiling for dialectic summaries.", minimum=100, maximum=50000, step=1, category="memory",
    ),
    "honcho.dialecticReasoningLevel": _select(
        "Reasoning effort for dialectic calls", "minimal", "low", "medium", "high", "max", category="memory",
    ),
    "honcho.observationMode": _select(
        "How turns become observations", "directional", "unified", category="memory",
    ),
    "honcho.recallMode": _select(
        "Recall strategy", "hybrid", "context", "tools", category="memory",
    ),
    "honcho.saveMessages": _bool("Persist chat turns to Honcho.", category="memory"),
    "honcho.sessionStrategy": _select(
        "Honcho session scoping", "per-session", "per-directory", "per-repo", "global", category="memory",
    ),
    "honcho.writeFrequency": _text("When messages are written: async, turn, session, or a positive number of turns.", category="memory"),
    "honcho.dialecticDepth": _num(
        "Dialectic reasoning passes per cycle.", minimum=1, maximum=3, step=1, category="memory",
    ),
    "honcho.contextCadence": _num("Turns between base-context refreshes.", minimum=1, maximum=100, step=1, category="memory"),
    "honcho.injectionFrequency": _select("When base context is included; dialectic keeps its own cadence.", "every-turn", "first-turn", category="memory"),
    "honcho.reasoningHeuristic": _bool("Use deeper reasoning for longer queries.", category="memory"),
    "honcho.reasoningLevelCap": _select("Maximum heuristic-selected reasoning effort.", "minimal", "low", "medium", "high", "max", category="memory"),
    "honcho.dialecticDynamic": _bool("Let the reasoning model select the effort for each call.", category="memory"),
    "honcho.recallSync": _bool("Wait within the request timeout for current-query recall.", category="memory"),
    "honcho.queryRewrite": _bool("Rewrite recall queries for retrieval.", category="memory"),
    "honcho.firstTurnBaseWait": _num("First-turn wait for base context in seconds.", minimum=0, maximum=30, category="memory"),
    "honcho.firstTurnDialecticWait": _num("First-turn wait for dialectic in seconds.", minimum=0, maximum=30, category="memory"),
    "honcho.messageMaxChars": _num("Maximum characters per message sent to Honcho.", minimum=1, maximum=100000, category="memory"),
    "honcho.dialecticMaxInputChars": _num("Maximum query characters sent to dialectic reasoning.", minimum=1, maximum=100000, category="memory"),
}

# ── Group surface display policy ─────────────────────────────────────────────────────────────────

_TELEGRAM_GROUP: Dict[str, Dict[str, Any]] = {
    "display.platforms.telegram_group.tool_progress": _select(
        "Tool progress notices in group chats", "off", "minimal", "full", category="display",
    ),
    "display.platforms.telegram_group.interim_assistant_messages": _bool(
        "Stream interim narration into group chats.", category="display",
    ),
    "display.platforms.telegram_group.streaming": _bool(
        "Stream group replies live (owner DM keeps its own setting).", category="display",
    ),
    "display.platforms.telegram_group.show_reasoning": _bool(
        "Show reasoning summaries in group chats.", category="display",
    ),
    "display.platforms.telegram_group.busy_ack_detail": _bool(
        "Verbose busy acknowledgements in group chats.", category="display",
    ),
    "display.platforms.telegram_group.long_running_notifications": _bool(
        "Long-running job notices in group chats.", category="display",
    ),
    "display.platforms.telegram_group.suppress_warning_notifications": _bool(
        "Route warnings away from the group (to the operator DM).", category="display",
    ),
    "display.platforms.telegram_group.cleanup_progress": _bool(
        "Clean up progress messages after the reply lands.", category="display",
    ),
    "display.platforms.telegram_group.busy_input_mode": _select(
        "Follow-ups while the companion is answering in a group", "queue", "interrupt", "steer", category="display",
    ),
}

LUNA_SCHEMA_FIELDS: Dict[str, Dict[str, Any]] = {}
LUNA_SCHEMA_FIELDS.update(_threshold_fields())
LUNA_SCHEMA_FIELDS.update(_STATIC)
LUNA_SCHEMA_FIELDS.update(_HONCHO)
LUNA_SCHEMA_FIELDS.update(_TELEGRAM_GROUP)

# Category tab order contribution (merged into the dashboard's category_order).
LUNA_CATEGORY_ORDER = ["companion"]

LUNA_SCHEMA_FIELDS.update({
    "luna.ambient.guard.max_jev_calls_per_hour": _num("Hard judgement attempt limit, including failures.", minimum=1, maximum=1000, step=1),
    "luna.ambient.guard.max_reported_cost_per_day": _num("Stop wake judgements after this reported daily cost in USD; attempt limit also applies when a provider omits costs.", minimum=0, maximum=100, step=0.1),
    "luna.memory.recall_timeout_seconds": _num("Maximum synchronous recall wait; chat continues while memory is degraded.", minimum=0.01, maximum=10, step=0.1),
    "luna.data.backup_days": _num("Backup archive retention in days (0 keeps all).", minimum=0, maximum=365, step=1),
    "luna.opencode.memory_budget_mib": _num("Native worker memory budget (320 MiB reserved per worker; at most four workers).", minimum=320, maximum=1280, step=320),
    "luna.access.group_host_access": _bool("Allow group members to use host tools. Owner opt-in; grant only to a trusted room."),
    "luna.access.group_toolsets": _list("Group capabilities; defaults permit web search and the scoped basic people directory."),
    "luna.conversation.enabled": _bool("Choose one reply at a time in each group/topic, with bounded bursts and a fixed recipient."),
    "luna.conversation.settle_seconds": _num("Gather a short incoming burst before choosing a question.", minimum=0, maximum=3, step=0.1),
    "luna.conversation.response_gap_seconds": _num("Minimum pause after a group reply before another answer.", minimum=0, maximum=30, step=0.5),
    "luna.conversation.max_pending": _num("Maximum distinct waiting requests per group/topic.", minimum=1, maximum=64, step=1),
    "luna.conversation.max_age_seconds": _num("Skip queued questions older than this, rather than sending late replies.", minimum=5, maximum=300, step=1),
    "luna.conversation.max_answer_age_seconds": _num("Stop a group turn that has run too long; never deliver its stale reply.", minimum=15, maximum=600, step=1),
    "luna.conversation.max_turns_per_burst": _num("Maximum questions selected from one burst; not every mention needs an answer.", minimum=1, maximum=10, step=1),
    "luna.conversation.burst_idle_seconds": _num("Quiet gap that starts a new burst.", minimum=2, maximum=60, step=1),
    "luna.conversation.max_turns_per_minute": _num("Per-group/topic response-attempt ceiling, including provider failures.", minimum=1, maximum=30, step=1),
    "luna.conversation.max_parallel_rooms": _num("Maximum active group/topic conversations for this bot, leaving other rooms bounded.", minimum=1, maximum=16, step=1),
    "luna.conversation.overload_notice": _bool("When some questions are skipped, send one brief invitation to tag again; at most once per minute."),
    "luna.character.name": _text("Companion name for wake judgement; empty derives from the persona title."),
    "luna.character.aliases": _list("Other names that address this companion."),
    "luna.output.language": _select("Reply language policy.", "auto", "english"),
    "luna.output.style_filter": _bool("Rewrite replies into casual chat rhythm. Off preserves the character's chosen style and DM formatting."),
    "luna.output.sentence_breaks": _bool("With casual chat style enabled, turn sentence punctuation into chat line breaks. Off keeps sentence punctuation and line layout."),
    "luna.output.max_chars": _num("Maximum group response size in UTF-16 units; always one delivery.", minimum=80, maximum=3500, step=1),
    "luna.ambient.budget.emergency_max_per_hour": _num("Independent hourly self-wake loop guard across all wake types.", minimum=1, maximum=100, step=1),
})
for _key, _value in LUNA_SCHEMA_FIELDS.items():
    if ".budget." in _key and "max_per" in _key and "emergency" not in _key:
        _value["nullable"] = True
        _value["description"] += " Empty/null means unlimited; zero disables this wake type."
