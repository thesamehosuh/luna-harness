"""Synthetic policy replay: multilingual content, another persona, floods and outages."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from luna_core import db
from luna_core.cascade import build_questions, is_substantive
from luna_core.wakes import WakeBudget, WakePolicy, DIRECTED, MESSAGE
from luna_core.judgement_guard import reserve

FIXTURE = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/companion_policy.json').read_text())


def test_character_and_language_replay(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'SOUL.md').write_text('# Sky\n\nA quiet companion.\n')
    (tmp_path / 'config.yaml').write_text('luna:\n  character:\n    aliases: [Skye]\n')
    questions = build_questions()
    assert 'Sky' in questions[0]['instructions'] and 'Skye' in questions[0]['instructions']
    assert 'Luna' not in json.dumps(questions)
    for case in FIXTURE['substantive']:
        assert is_substantive(case['text'], min_chars=3) is case['expected']


def test_unlimited_conversation_budget_keeps_independent_flood_guard(tmp_path):
    conn = db.connect(tmp_path / 'state.db');db.init_db(conn)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    budget = WakeBudget(conn, WakePolicy())
    assert budget.policy.directed_max_per_day is None
    for index in range(FIXTURE['emergency_guard']['max_per_hour']):
        assert budget.can_wake(DIRECTED, now)[0]
        budget.record(DIRECTED, 'synthetic-room', trigger_message_id=str(index), now=now)
    assert budget.can_wake(DIRECTED, now)[0] is FIXTURE['emergency_guard']['expected_after_12']
    assert not budget.can_wake(MESSAGE, now)[0]
    assert budget.can_wake(DIRECTED, now + timedelta(hours=1, seconds=1))[0] is FIXTURE['emergency_guard']['expected_next_hour']
    conn.close()


def test_outages_and_missing_usage_cannot_escape_attempt_budget(tmp_path):
    conn = db.connect(tmp_path / 'state.db');db.init_db(conn)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert reserve(conn, now, calls_per_hour=2)
    assert reserve(conn, now, calls_per_hour=2)
    assert not reserve(conn, now, calls_per_hour=2)
    assert reserve(conn, now + timedelta(hours=1, seconds=1), calls_per_hour=2)
    conn.execute("INSERT INTO jev_usage(created_at,route,cost_usd) VALUES (?,'paid',1.1)", (now.isoformat(),));conn.commit()
    assert not reserve(conn, now + timedelta(hours=2), calls_per_hour=2, cost_per_day=1.0)
    conn.close()
