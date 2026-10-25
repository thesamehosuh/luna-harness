"""Dashboard status and actual effective Honcho tuning, matching `luna honcho status`."""
from luna_cli.config_schema import _HONCHO

ATTRIBUTES = {
    "contextTokens": "context_tokens", "dialecticCadence": "dialectic_cadence",
    "dialecticMaxChars": "dialectic_max_chars", "dialecticReasoningLevel": "dialectic_reasoning_level",
    "observationMode": "observation_mode", "recallMode": "recall_mode", "saveMessages": "save_messages",
    "sessionStrategy": "session_strategy", "writeFrequency": "write_frequency", "dialecticDepth": "dialectic_depth",
    "contextCadence": "context_cadence", "injectionFrequency": "injection_frequency", "reasoningHeuristic": "reasoning_heuristic",
    "reasoningLevelCap": "reasoning_level_cap", "dialecticDynamic": "dialectic_dynamic", "recallSync": "recall_sync",
    "queryRewrite": "query_rewrite", "firstTurnBaseWait": "first_turn_base_wait", "firstTurnDialecticWait": "first_turn_dialectic_wait",
    "messageMaxChars": "message_max_chars", "dialecticMaxInputChars": "dialectic_max_input_chars",
}
LABELS = {
    "dialecticCadence": "Dialectic every N turns", "contextCadence": "Refresh context every N turns",
    "dialecticReasoningLevel": "Dialectic reasoning level", "contextTokens": "Recalled context token budget",
    "dialecticDepth": "Dialectic passes", "dialecticMaxChars": "Dialectic result character limit",
    "reasoningLevelCap": "Reasoning level cap", "reasoningHeuristic": "Adaptive reasoning effort",
    "recallMode": "Recall mode", "observationMode": "Observation mode",
    "writeFrequency": "Write frequency", "saveMessages": "Save conversation messages",
    "sessionStrategy": "Session strategy", "injectionFrequency": "Recall injection frequency",
    "dialecticDynamic": "Adaptive dialectic cadence", "recallSync": "Wait for recall",
    "queryRewrite": "Rewrite recall queries", "firstTurnBaseWait": "First-turn context wait (seconds)",
    "firstTurnDialecticWait": "First-turn dialectic wait (seconds)",
    "messageMaxChars": "Message character limit", "dialecticMaxInputChars": "Dialectic input character limit",
}


def report():
    from plugins.memory.honcho.client import HonchoClientConfig
    from luna_core import config_read, readiness
    from luna_core.memory_reasoning import public_route
    cfg = HonchoClientConfig.from_global_config()
    values = {key: getattr(cfg, attr) for key, attr in ATTRIBUTES.items()}
    fields = [{"key": key, "label": LABELS.get(key, key), "schema": _HONCHO["honcho." + key], "value": values[key]}
              for key in ATTRIBUTES]
    return {"fields": fields, "reasoning": public_route(), "verification": readiness.get("memory"),
            "status": {"enabled": cfg.enabled and config_read.section("luna", "setup", "memory", default="enabled") == "enabled",
                       "host": cfg.host, "workspace": cfg.workspace_id, "ai_peer": cfg.ai_peer, "user_peer": cfg.peer_name,
                       "base_url": cfg.base_url, "auth_configured": bool(cfg.api_key), "session_strategy": cfg.session_strategy,
                       "observation": {"user_me": cfg.user_observe_me, "user_others": cfg.user_observe_others,
                                       "ai_me": cfg.ai_observe_me, "ai_others": cfg.ai_observe_others}}}
