"""User-authored judgment rubrics and additional wake conditions.

Custom conditions can veto a wake, never bypass the cascade or delivery guards.
The fixed question IDs/types keep the deterministic composer meaningful.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy

DIRECTED_PROMPT = ('[Someone in the group is talking to you. Reply to the message below and nothing '
                   'else. The later "Room background" section is just the room around it — it is not '
                   'what you were asked about. If it does not need an answer, return exactly NO_REPLY; '
                   'never answer someone else instead.]')
MESSAGE_PROMPT = ('[A moment in the group you could join ({contribution_type}). '
                  'Speak only if you actually have something to add.]')
WAKE_PROMPTS = {"directed": DIRECTED_PROMPT, "message": MESSAGE_PROMPT}


def text(value, label, *, empty=False):
    if not isinstance(value, str) or len(value) > 12000 or (not empty and not value.strip()):
        raise ValueError(f"{label} expects {'up to 12000 characters' if empty else '1–12000 characters of text'}")
    return value


def validate_policy(value, catalog):
    if not isinstance(value, dict) or set(value) - {"questions", "rules"}:
        raise ValueError("decision expects questions and rules")
    overrides = value.get("questions", {})
    rules = value.get("rules", [])
    if not isinstance(overrides, dict) or not isinstance(rules, list) or len(rules) > 30:
        raise ValueError("decision expects a question mapping and up to 30 rules")
    known = {q["id"]: q for q in catalog}
    clean = {}
    for qid, patch in overrides.items():
        if qid not in known or not isinstance(patch, dict) or set(patch) - {"instructions", "criteria"}:
            raise ValueError(f"Unknown judgment or field: {qid}")
        entry = {}
        if "instructions" in patch:
            entry["instructions"] = text(patch["instructions"], qid)
        if "criteria" in patch:
            criteria, original = patch["criteria"], known[qid]["criteria"]
            if isinstance(original, list):
                if not isinstance(criteria, list) or len(criteria) != len(original):
                    raise ValueError(f"{qid} must keep its {len(original)} score levels")
                entry["criteria"] = [text(v, qid) for v in criteria]
            else:
                if not isinstance(criteria, dict) or set(criteria) != set(original):
                    raise ValueError(f"{qid} must keep its answer options")
                entry["criteria"] = {k: text(v, qid, empty=True) for k, v in criteria.items()}
        clean[qid] = entry
    clean_rules, seen = [], set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) - {"id", "name", "instructions", "action", "threshold", "enabled"}:
            raise ValueError("Invalid custom condition")
        rid = rule.get("id")
        if not isinstance(rid, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", rid) or rid in seen:
            raise ValueError("Conditions need unique IDs (letters, numbers, hyphens or underscores)")
        seen.add(rid)
        action = rule.get("action", "both")
        threshold = rule.get("threshold", 0.8)
        enabled = rule.get("enabled", True)
        if action not in {"message", "reaction", "both"} or not isinstance(enabled, bool):
            raise ValueError("Condition action must be message, reaction or both; enabled must be true/false")
        if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("Condition confidence must be between 0 and 1")
        clean_rules.append({"id": rid, "name": text(rule.get("name"), "Condition name"),
                            "instructions": text(rule.get("instructions"), "Condition prompt"),
                            "action": action, "threshold": threshold, "enabled": enabled})
    return {"questions": clean, "rules": clean_rules}


def apply_policy(questions, policy, reaction_criteria=None):
    questions = deepcopy(questions)
    for question in questions:
        question.update(policy["questions"].get(question["id"], {}))
        if question["id"] == "reaction_emoji" and reaction_criteria:
            question["criteria"].update({k: v for k, v in reaction_criteria.items() if k in question["criteria"]})
    for rule in policy["rules"]:
        if rule["enabled"]:
            questions.append({"id": "custom_" + rule["id"], "type": "noul",
                              "instructions": rule["instructions"],
                              "criteria": {"true": "condition met; may proceed", "false": "condition not met; stay silent"}})
    return questions


def blocked_condition(decision, answers, policy):
    if not decision.should_wake:
        return None
    for rule in policy["rules"]:
        if not rule["enabled"] or rule["action"] not in ("both", decision.action):
            continue
        answer = answers.get("custom_" + rule["id"])
        if answer is None or answer.type != "noul":
            return rule["name"]
        try:
            if answer.as_probability() < rule["threshold"]:
                return rule["name"]
        except Exception:
            return rule["name"]
    return None
