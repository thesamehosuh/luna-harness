"""Offline recomposition of stored judgments. Never constructs a provider client."""
import json
from pathlib import Path
from luna_core import db
from luna_core.cascade import CascadeConfig, compose, build_questions
from luna_core.jev import JevAnswer


def replay(path, config, limit=25):
    ambient = ((config.get("luna") or {}).get("ambient") or {})
    thresholds = CascadeConfig()
    for key, value in (ambient.get("thresholds") or {}).items():
        if key in thresholds.__dict__ and isinstance(value, (int, float)):
            setattr(thresholds, key, value)
    allowed = (ambient.get("reactions") or {}).get("allowed") or []
    from luna_core.behaviour_policy import validate_policy, apply_policy, blocked_condition
    policy = validate_policy(ambient.get("decision") or {}, build_questions(allowed or None))
    questions = apply_policy(build_questions(allowed or None), policy,
                             (ambient.get("reactions") or {}).get("criteria") or {})
    rows = []
    if Path(path).exists():
        conn = db.connect(path, read_only=True)
        try:
            import sqlite3
            try:
                rows = conn.execute("SELECT * FROM ambient_judgments ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()
            except sqlite3.OperationalError:
                rows = []
        finally:
            conn.close()
    report = []
    for row in reversed(rows):
        try:
            answers = {key: JevAnswer(**value) for key, value in json.loads(row["answers"]).items()}
            decision = compose(answers, config=thresholds, reactions_enabled=bool(allowed), allowed_reactions=allowed,
                               candidate_text=row["candidate_text"], questions=questions)
            if blocked := blocked_condition(decision, answers, policy):
                from dataclasses import replace
                decision = replace(decision, action="silent", reason=f"custom condition: {blocked}")
            report.append({"chat_id": row["chat_id"], "thread_id": row["thread_id"],
                           "message_id": row["message_id"], "timestamp": row["created_at"],
                           "original_action": row["original_action"], "action": decision.action,
                           "reason": decision.reason, "value": decision.value})
        except (ValueError, TypeError, KeyError):
            continue
    return {"ok": True, "report": report, "network_calls": 0,
            "output": f"Recomposed {len(report)} stored judgments offline. Timing/admission/delivery and changed rubric text are not re-evaluated. New conditions without saved answers fail closed.",
            "errors": "", "mode": "stored-judgments"}
