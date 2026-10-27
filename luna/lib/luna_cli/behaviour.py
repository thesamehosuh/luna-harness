"""Behaviour config (PRODUCT_PLAN P4): the self-wake knobs behind the Behaviour page.

``luna.ambient.*`` reads/writes with the comment-preserving editor — dry-run toggle, budget and
cooldowns, mention/reaction policy, and the jev route chain (providers replaced wholesale so a
removed route cannot linger).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from luna_core import configedit, settings
from luna_cli import tune


def _ambient() -> Dict[str, Any]:
    from luna_core.config_read import with_defaults
    data = configedit.read_config_value(with_defaults(tune._load_yaml(tune.config_path())), ["luna", "ambient"]) or {}
    return data if isinstance(data, dict) else {}


def _conversation():
    # Read through the settings transaction, including staged writes. The gateway's
    # cached config reader is deliberately not used by dashboard edit transactions.
    from luna_core.config_read import with_defaults
    from luna_core.room_dispatch import validate_policy
    data = with_defaults(tune._load_yaml(tune.config_path()))
    return validate_policy(configedit.read_config_value(data, ["luna", "conversation"]) or {})


@settings.transactional
def behaviour_bundle() -> Dict[str, Any]:
    from luna_core.config_read import with_defaults
    ambient = _ambient()
    budget = ambient.get("budget") if isinstance(ambient.get("budget"), dict) else {}
    from luna_core.wakes import WakePolicy
    # Obsolete keys in older profiles are not runtime knobs. Re-emitting them made an
    # unrelated group selection fail validation when the dashboard saved its whole draft.
    budget = {name: budget.get(name, default) for name, default in WakePolicy().as_dict().items()}
    for name, value in budget.items():
        if value == 1000000000 and (name.endswith("max_per_day") or name.endswith("max_per_week")):
            budget[name] = None
    reactions = ambient.get("reactions") if isinstance(ambient.get("reactions"), dict) else {}
    jev = ambient.get("jev") if isinstance(ambient.get("jev"), dict) else {}
    from luna_core.cascade import build_questions, REACTION_CRITERIA
    from luna_core.behaviour_policy import WAKE_PROMPTS
    providers = jev.get("providers") if isinstance(jev.get("providers"), dict) else {}
    from luna_core.room_dispatch import BOUNDS
    from luna_cli.conversation_status import report
    raw = tune._load_yaml(tune.config_path())
    watched = ((raw.get("luna") or {}).get("ambient") or {}).get("watched_chats")
    if watched is None:
        # Display the effective legacy choice, so unchecking it explicitly disables watching.
        selected = ((raw.get("luna") or {}).get("room") or {}).get("chat_id")
        allowed = (raw.get("telegram") or {}).get("group_allowed_chats") or []
        watched = [str(selected)] if selected else [str(allowed[0])] if len(allowed) == 1 else []
    return {
        "revision": settings.revision(),
        "conversation": _conversation().__dict__,
        "conversation_bounds": BOUNDS,
        "conversation_status": report(),
        "enabled": bool(ambient.get("enabled")) and configedit.read_config_value(
            with_defaults(raw),
            ["luna", "setup", "jev"]) in (None, "enabled"),
        "watched_chats": list(watched),
        "available_chats": list(dict.fromkeys([str(item) for item in (raw.get("telegram") or {}).get("group_allowed_chats", [])]
                                + ([str(((raw.get("luna") or {}).get("room") or {}).get("chat_id"))]
                                   if ((raw.get("luna") or {}).get("room") or {}).get("chat_id") else []))),
        "dry_run": ambient.get("dry_run"),
        "room_register": ambient.get("room_register", ""),
        "settle_seconds": ambient.get("settle_seconds"),
        "poll_seconds": ambient.get("poll_seconds"),
        "stale_after_minutes": ambient.get("stale_after_minutes"),
        "budget": budget,
        "mention_fallback": list(ambient.get("mention_fallback") or []),
        "reactions": {"allowed": list(reactions.get("allowed") or []), "criteria": dict(reactions.get("criteria") or {})},
        "reaction_defaults": REACTION_CRITERIA,
        "decision": ambient.get("decision") or {"questions": {}, "rules": []},
        "question_defaults": build_questions(list(REACTION_CRITERIA)),
        "wake_prompts": dict(ambient.get("wake_prompts") or {}),
        "wake_prompt_defaults": WAKE_PROMPTS,
        "jev": {
            "timeout_seconds": jev.get("timeout_seconds"),
            "route": list(jev.get("route") or []),
            "providers": providers,
        },
    }


# Writes: partial update; each accepted top-level key is one surgical config write.
_ACCEPTED = ("enabled", "dry_run", "room_register", "settle_seconds", "poll_seconds",
             "stale_after_minutes", "watched_chats", "budget", "mention_fallback", "reactions", "jev", "conversation",
             "decision", "wake_prompts")

_NUM_BOUNDS = {
    "settle_seconds": (0, 600),
    "poll_seconds": (1, 300),
    "stale_after_minutes": (1, 1440),
}
_BUDGET_BOUNDS = (0, 10 ** 6)


@settings.transactional
def write_behaviour(updates: Dict[str, Any]) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    text = settings.read(tune.config_path())
    wrote = False
    for key, value in updates.items():
        if key not in _ACCEPTED:
            results[key] = {"ok": False, "error": f"unknown behaviour key {key!r}"}
            continue
        try:
            value = _validated(key, value)
            path = ["luna", "conversation"] if key == "conversation" else ["luna", "ambient", key]
            text = configedit.write_config_value(text, path, value)
            if key == "enabled":
                # The explicit master switch also settles the optional onboarding gate.
                text = configedit.write_config_value(text, ["luna", "setup", "jev"], "enabled" if value else "skipped")
            results[key] = {"ok": True}
            wrote = True
        except configedit.ConfigEditError as exc:
            results[key] = {"ok": False, "error": str(exc)}
    if any(not result["ok"] for result in results.values()):
        for result in results.values():
            if result["ok"]:
                result.update(ok=False, error="No changes applied: another field is invalid")
    elif wrote:
        settings.write(tune.config_path(), text)
    return {"results": results, "behaviour": behaviour_bundle()}


def _validated(key: str, value: Any) -> Any:
    if key in ("decision", "wake_prompts"):
        from luna_core.behaviour_policy import validate_policy, text as validate_text, WAKE_PROMPTS
        from luna_core.cascade import build_questions, REACTION_CRITERIA
        try:
            if key == "decision":
                return validate_policy(value, build_questions(list(REACTION_CRITERIA)))
            if not isinstance(value, dict) or set(value) - set(WAKE_PROMPTS):
                raise ValueError("wake_prompts expects directed and message prompts")
            return {k: validate_text(v, k) for k, v in value.items()}
        except ValueError as exc:
            raise configedit.ConfigEditError(str(exc)) from exc
    if key == "watched_chats":
        if not isinstance(value, list) or len(value) > 100 or any(not isinstance(item, str) or not item.strip() for item in value):
            raise configedit.ConfigEditError("watched_chats expects up to 100 group IDs")
        from luna_core.config_read import with_defaults
        cfg = with_defaults(tune._load_yaml(tune.config_path()))
        allowed = {str(item) for item in (cfg.get("telegram") or {}).get("group_allowed_chats", [])}
        selected = ((cfg.get("luna") or {}).get("room") or {}).get("chat_id")
        if selected:
            allowed.add(str(selected))
        if any(item not in allowed for item in value):
            raise configedit.ConfigEditError("Choose only Telegram groups already allowed in Channels")
        return list(dict.fromkeys(value))
    if key == "conversation":
        from luna_core.room_dispatch import validate_policy
        if not isinstance(value, dict):
            raise configedit.ConfigEditError("conversation expects a mapping")
        try:
            return validate_policy({**_conversation().__dict__, **value}).__dict__
        except ValueError as exc:
            raise configedit.ConfigEditError(str(exc)) from exc
    if key in _NUM_BOUNDS:
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise configedit.ConfigEditError(f"{key} expects an integer") from None
        low, high = _NUM_BOUNDS[key]
        if not low <= value <= high:
            raise configedit.ConfigEditError(f"{key} must be between {low} and {high}")
        return value
    if key in ("enabled", "dry_run"):
        if value not in (True, False):
            raise configedit.ConfigEditError(f"{key} expects true/false")
        return value
    if key == "room_register":
        if not isinstance(value, str):
            raise configedit.ConfigEditError("room_register expects text")
        return value.strip()
    if key in ("mention_fallback",):
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise configedit.ConfigEditError("mention_fallback expects a list of regex strings")
        return [x for x in value if x.strip()]
    if key == "reactions":
        if not isinstance(value, dict):
            raise configedit.ConfigEditError("reactions expects a mapping")
        allowed = value.get("allowed", [])
        if not isinstance(allowed, list) or len(allowed) > 100 or any(not isinstance(x, str) or not x.strip() or len(x) > 32 for x in allowed):
            raise configedit.ConfigEditError("reactions.allowed expects up to 100 emoji strings")
        criteria = value.get("criteria", {})
        if not isinstance(criteria, dict) or len(criteria) > 100 or any(not isinstance(k, str) or not isinstance(v, str) or len(k) > 32 or len(v) > 12000 for k, v in criteria.items()):
            raise configedit.ConfigEditError("reactions.criteria expects emoji descriptions")
        return {"allowed": list(dict.fromkeys(allowed)), "criteria": criteria}
    if key == "budget":
        if not isinstance(value, dict):
            raise configedit.ConfigEditError("budget expects a mapping")
        out: Dict[str, Any] = {}
        from dataclasses import fields
        from luna_core.wakes import WakePolicy
        known = {item.name for item in fields(WakePolicy)}
        for name, raw in value.items():
            if name not in known:
                raise configedit.ConfigEditError(f"unknown budget key {name!r}")
            if name == "emergency_max_per_hour" and (not isinstance(raw, int) or isinstance(raw, bool) or not 1 <= raw <= 100):
                raise configedit.ConfigEditError("emergency_max_per_hour must be between 1 and 100")
            if raw is None:
                if not (name.endswith("max_per_day") or name.endswith("max_per_week")):
                    raise configedit.ConfigEditError(f"budget.{name} cannot be unlimited")
                out[str(name)] = None
                continue
            try:
                if isinstance(raw, bool) or int(raw) != raw:
                    raise ValueError()
                number = int(raw)
            except (TypeError, ValueError):
                raise configedit.ConfigEditError(f"budget.{name} expects an integer") from None
            # Old templates represented unlimited as one billion; migrate on save.
            if number == 1000000000 and (name.endswith("max_per_day") or name.endswith("max_per_week")):
                out[str(name)] = None
                continue
            high = 1440 if name.endswith("cooldown_minutes") else _BUDGET_BOUNDS[1]
            if not _BUDGET_BOUNDS[0] <= number <= high:
                raise configedit.ConfigEditError(f"budget.{name} out of range")
            out[str(name)] = number
        return out
    if key == "jev":
        return _validated_jev(value)
    return value


def _validated_jev(value: Any) -> Dict[str, Any]:
    """Route chain: names in ``route`` must resolve (registry entries need a model)."""
    if not isinstance(value, dict):
        raise configedit.ConfigEditError("jev expects a mapping")
    route = value.get("route") or []
    providers = value.get("providers") or {}
    if not isinstance(route, list) or not isinstance(providers, dict):
        raise configedit.ConfigEditError("jev.route must be a list and jev.providers a mapping")
    out: Dict[str, Any] = {}
    timeout = value.get("timeout_seconds")
    if timeout is not None:
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            raise configedit.ConfigEditError("jev.timeout_seconds expects an integer") from None
        if not 1 <= timeout <= 60:
            raise configedit.ConfigEditError("jev.timeout_seconds must be between 1 and 60")
        out["timeout_seconds"] = timeout
    clean_providers: Dict[str, Any] = {}
    for name, entry in providers.items():
        if not isinstance(name, str) or not name.strip():
            raise configedit.ConfigEditError("Providers need non-empty names")
        if not isinstance(entry, dict):
            raise configedit.ConfigEditError(f"jev.providers.{name} must be a mapping")
        if not str(entry.get("model") or "").strip():
            raise configedit.ConfigEditError(f"jev.providers.{name} needs a model")
        if "instructions" in entry and (not isinstance(entry["instructions"], str) or len(entry["instructions"]) > 12000):
            raise configedit.ConfigEditError(f"jev.providers.{name}.instructions expects up to 12000 characters")
        if "timeout_seconds" in entry:
            value_timeout = entry["timeout_seconds"]
            if type(value_timeout) not in (int, float) or not 0 < value_timeout <= 60:
                raise configedit.ConfigEditError(f"jev.providers.{name}.timeout_seconds must be between 0 and 60")
        clean_providers[str(name)] = {
            k: entry[k] for k in ("base_url", "model", "api_key_env", "endpoint", "instructions", "tier", "timeout_seconds")
            if entry.get(k) not in (None, "")
        }
    for name in route:
        if not isinstance(name, str):
            raise configedit.ConfigEditError("jev.route entries must be provider names")
        if name not in clean_providers:
            raise configedit.ConfigEditError(f"jev.route references unknown provider {name!r}")
    out["route"] = [str(n) for n in route]
    out["providers"] = clean_providers
    return out
