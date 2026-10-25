"""Differential, offline checks against a legacy Luna checkout (never imports its services).

Run with a supported development Python:
  python luna/tools/verify_port.py /path/to/project-luna
Only synthetic fixtures and in-memory databases are used. Neither checkout nor runtime is written.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def probe(root: Path, fixtures: Path) -> dict:
    sys.path[:0] = [str(root / "luna/lib"), str(root)]
    import dataclasses
    import random
    from datetime import datetime, timezone

    from luna_core import cascade, db
    from luna_core.identity import IdentityRegistry
    from luna_core.jev import JevAnswer
    from luna_core.room import build_room_block

    rng = random.Random(20261024)
    config = cascade.CascadeConfig()
    probabilities = [0, 0.05, 0.35, 0.4, 0.42, 0.43, 0.55, 0.6, 0.66, 0.7, 0.9, 1.0]
    questions = cascade.build_questions(["👍", "🤣", "😭"])
    decisions = []
    for index in range(512):
        answers = {}
        for question in questions:
            qid, kind = question["id"], question["type"]
            value = rng.choice(probabilities)
            if kind == "choice":
                value = rng.choice(list(question["criteria"]))
            elif kind == "score":
                value = rng.choice([0, 1, 2])
            answers[qid] = JevAnswer(id=qid, type=kind, value=value, confidence=0.9)
        decision = cascade.compose(answers, config=config, reactions_enabled=index % 2 == 0,
                                   allowed_reactions=["👍", "🤣", "😭"],
                                   ctx=cascade.Stage0Context(5, 20), candidate_text="a synthetic room question?")
        decisions.append(dataclasses.asdict(decision))
    rooms = {}
    for path in sorted(fixtures.glob("*.json")):
        fixture = json.loads(path.read_text())
        conn = db.connect(":memory:")
        db.init_db(conn)
        registry = IdentityRegistry(conn)
        for uid, identity in fixture.get("identity", {}).items():
            registry.set_manual("telegram", uid, peer_id=identity["peer_id"], display_name=identity.get("display_name"))
        for message in fixture["messages"]:
            conn.execute(
                "INSERT INTO messages(message_id, chat_id, user_id, user_name, peer_id, content, timestamp, "
                "reply_to_message_id, is_bot, observed) VALUES (?,?,?,?,?,?,?,?,0,1)",
                (message["message_id"], fixture["chat_id"], message["user_id"], message["user_name"],
                 registry.resolve("telegram", message["user_id"]), message["content"], message["timestamp"], message["reply_to_message_id"]),
            )
        conn.commit()
        block = build_room_block(conn, fixture["chat_id"], current_message_id=fixture["current_message_id"],
                                registry=registry, now=datetime(2026, 1, 1, 12, 15, tzinfo=timezone.utc))
        rooms[path.name] = {"text": block.text, "aliases": registry.alias_map("telegram")}
        conn.close()
    return {"threshold_defaults": config.as_dict(), "questions": questions, "decisions": decisions, "rooms": rooms}


def compare(legacy: Path, current: Path) -> dict:
    fixtures = current / "luna/tests/fixtures/room"
    outputs = []
    with tempfile.TemporaryDirectory(prefix="luna-port-probe-") as tmp:
        for root in (legacy, current):
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("LUNA_", "HERMES_", "PYTHONPATH")) and not key.endswith(("_API_KEY", "_TOKEN"))}
            env.update(HERMES_HOME=tmp, LUNA_HOME=tmp, PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--probe", str(root), str(fixtures)],
                                    cwd=tmp, env=env, capture_output=True, text=True, check=True)
            outputs.append(json.loads(result.stdout))
    mismatches = [key for key in outputs[0] if outputs[0][key] != outputs[1][key]]
    return {"ok": not mismatches, "wake_decisions": len(outputs[0]["decisions"]),
            "room_fixtures": len(outputs[0]["rooms"]), "mismatches": mismatches,
            "scope": "deterministic composition, thresholds, questions, identity, room/reply reconstruction"}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--probe":
        print(json.dumps(probe(Path(sys.argv[2]), Path(sys.argv[3])), ensure_ascii=False, sort_keys=True))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("legacy", type=Path)
        args = parser.parse_args()
        report = compare(args.legacy.expanduser().resolve(), Path(__file__).resolve().parents[2])
        print(json.dumps(report, indent=2))
        sys.exit(0 if report["ok"] else 1)
