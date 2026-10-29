"""Regressions for the public-room ambient/Jev audit. Synthetic and network-free."""
from datetime import datetime, timedelta, timezone
import asyncio
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error
from unittest.mock import patch

import pytest
from luna_core import db
from luna_core import cascade as c
from luna_core.jev import (JevAnswer, JevClient, JevError, build_client,
                           noul, parse_answers, profile_attempt_hooks)
from luna_core.room import record_inbound

ROOT = Path(__file__).resolve().parents[3]
CHAT = '-1000000000000-test'
NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_answers(questions=None):
    questions = questions or c.build_questions()
    result = {}
    for question in questions:
        kind, qid = question['type'], question['id']
        value = (0.05 if kind == 'noul' else 0 if kind == 'score' else next(iter(question['criteria'])))
        if qid in {c.ADD_VALUE, c.OPEN_Q, c.TOPIC_FIT, c.ADDRESSED_DIRECT, c.MESSAGE_FIT}:
            value = 0.95
        if qid == c.TIMELINESS:
            value = 1
        result[qid] = JevAnswer(qid, kind, value)
    return result


def payload(questions=None):
    return {'answers': {key: {'type': answer.type, answer.type: answer.value}
                        for key, answer in valid_answers(questions).items()}}


@pytest.fixture
def system(tmp_path, monkeypatch):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setenv('LUNA_HOME', str(tmp_path))
    for key in ('LUNA_CHAT_ID', 'LUNA_INDEX_DB', 'LUNA_ROOM_SESSION_KEY', 'LUNA_JEV_BASE_URL',
                'LUNA_JEV_MODEL', 'LUNA_JEV_API_KEY_ENV', 'LUNA_JEV_TIMEOUT'):
        monkeypatch.delenv(key, raising=False)
    token = set_hermes_home_override(tmp_path)
    cfg = {'telegram': {'group_allowed_chats': [CHAT]}, 'luna': {
        'setup': {'jev': 'enabled'}, 'room': {'chat_id': CHAT},
        'character': {'name': 'Mira'}, 'ambient': {'enabled': True, 'dry_run': False,
        'settle_seconds': 0, 'jev': {'route': ['local'], 'providers': {
            'local': {'model': 'synthetic-local', 'base_url': 'http://127.0.0.1:9/v1'}}}}}}
    (tmp_path / 'config.yaml').write_text(json.dumps(cfg))
    (tmp_path / '.env').write_text('# synthetic only\n')
    (tmp_path / 'SOUL.md').write_text('# Mira\n')
    mod = load('luna/plugins/luna-ambient/__init__.py', 'ambient_regression')
    monkeypatch.setattr(mod, 'datetime', Clock)
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **kw: pytest.fail('Network disabled'))
    conn = db.connect(tmp_path / 'luna-state.db')
    db.init_db(conn)
    try:
        yield tmp_path, cfg, mod, conn
    finally:
        mod._shutdown()
        conn.close()
        reset_hermes_home_override(token)


def add(conn, mid='1', text='Mira, can you check this?', *, chat=CHAT, topic='', reply=None,
        bot=False, peer=None, timestamp=None, name='Synthetic member'):
    record_inbound(conn, message_id=mid, chat_id=chat, thread_id=topic, user_id='synthetic-bot' if bot else 'synthetic-user',
                   user_name=name, content=text, reply_to_message_id=reply, peer_id=peer, is_bot=bot,
                   timestamp=(timestamp or NOW - timedelta(seconds=1)).isoformat())


def test_named_keyless_primary_honors_endpoint_without_inheriting_key(system, monkeypatch):
    home, cfg, mod, conn = system
    entry = cfg['luna']['ambient']['jev']['providers']['local']
    entry.update(endpoint='http://127.0.0.1:9/custom', instructions='synthetic')
    (home / 'config.yaml').write_text(json.dumps(cfg))
    monkeypatch.setattr(mod, '_jev_api_key', lambda key: 'SYNTHETIC_UNRELATED')
    client = mod._jev_client()
    assert client.api_key == ''
    assert client.endpoint.endswith('/custom')
    assert client.instructions == 'synthetic'
    for route in ([], ['typo']):
        with pytest.raises(JevError, match='no valid'):
            build_client({'route': route, 'providers': {}}, lambda key: 'synthetic')


def test_factory_uses_scoped_keys_for_every_route(system, monkeypatch):
    monkeypatch.setenv('FALLBACK_KEY', 'SYNTHETIC_OTHER_PROFILE')
    config = {'route': ['first', 'second'], 'providers': {
        'first': {'model': 'first', 'api_key_env': 'FIRST_KEY'},
        'second': {'model': 'second', 'api_key_env': 'FALLBACK_KEY'}}}
    seen = []
    def ask(client, state, questions):
        seen.append((client.model, client.api_key))
        if client.model == 'first':
            raise JevError('quota', status=429)
        return valid_answers(questions)
    monkeypatch.setattr(JevClient, 'ask', ask)
    client = build_client(config, lambda key: 'SYNTHETIC_SCOPED_' + key)
    client.ask({}, c.build_questions())
    assert seen == [('first', 'SYNTHETIC_SCOPED_FIRST_KEY'), ('second', 'SYNTHETIC_SCOPED_FALLBACK_KEY')]


@pytest.mark.parametrize('bad', ['unparseable', float('nan'), float('inf'), -0.1, 1.1, True])
def test_invalid_privacy_answer_cannot_wake(bad):
    answers = valid_answers()
    answers[c.PRIVATE].value = bad
    assert not c.compose(answers, config=c.CascadeConfig()).should_wake
    body = payload()
    body['answers'][c.PRIVATE]['noul'] = bad
    with pytest.raises(JevError):
        parse_answers(body, c.build_questions())


def test_wrong_type_choice_and_distribution_fail_closed():
    for answer in ({'type': 'score', 'score': 0.5},
                   {'type': 'noul', 'noul': 0.5, 'confidence': float('nan')},
                   {'type': 'noul', 'noul': 0.5, 'probabilities': {'true': 0.8, 'false': 0.8}}):
        with pytest.raises(JevError):
            parse_answers({'answers': {'q': answer}}, [noul('q', 'synthetic')])
    with pytest.raises(JevError):
        parse_answers({'answers': {'q': {'type': 'choice', 'choice': 'unknown'}}},
                      [{'id': 'q', 'type': 'choice', 'criteria': {'known': 'x'}}])


def test_bad_json_does_not_advance_to_paid_route(system, monkeypatch):
    calls = []
    def post(request, **kwargs):
        calls.append(request.full_url)
        return io.BytesIO(b'not JSON')
    monkeypatch.setattr('urllib.request.urlopen', post)
    client = build_client({'route': ['free', 'paid'], 'providers': {
        'free': {'model': 'free', 'base_url': 'http://127.0.0.1:9/free'},
        'paid': {'model': 'paid', 'base_url': 'http://127.0.0.1:9/paid'}}}, lambda key: '')
    with pytest.raises(JevError, match='protocol'):
        client.ask({}, [noul('q', 'synthetic')])
    assert len(calls) == 1 and '/free/' in calls[0]


def test_attempt_guard_covers_retries_and_fallbacks(system, monkeypatch):
    home, cfg, mod, conn = system
    count = []
    def reject(request, **kwargs):
        count.append(1)
        raise urllib.error.HTTPError(request.full_url, 429, 'quota', {}, io.BytesIO(b'synthetic'))
    monkeypatch.setattr('urllib.request.urlopen', reject)
    guard, observer = profile_attempt_hooks(home / 'luna-state.db', {'max_jev_calls_per_hour': 2})
    client = build_client({'route': ['a', 'b'], 'providers': {'a': {'model': 'a'}, 'b': {'model': 'b'}}},
                          lambda key: '', guard=guard, observer=observer)
    client.client.primary._sleep = lambda seconds: None
    with pytest.raises(JevError, match='resource guard'):
        client.ask({}, [noul('q', 'synthetic')])
    assert len(count) == 2
    assert conn.execute('SELECT COUNT(*) FROM jev_usage').fetchone()[0] == 2


def test_one_deadline_bounds_route_chain(system, monkeypatch):
    client = build_client({'timeout_seconds': 1, 'route': ['a', 'b'], 'providers': {'a': {'model': 'a'}, 'b': {'model': 'b'}}}, lambda key: '')
    clock = [0.0]
    client.operation.clock = lambda: clock[0]
    calls = []
    def post(request, **kwargs):
        calls.append(kwargs['timeout'])
        clock[0] = 2
        raise TimeoutError('synthetic timeout')
    monkeypatch.setattr('urllib.request.urlopen', post)
    with pytest.raises(JevError, match='deadline'):
        client.ask({}, [noul('q', 'synthetic')])
    assert len(calls) == 1 and calls[0] <= 1


def test_usage_without_price_is_recorded_as_unknown(system):
    home, cfg, mod, conn = system
    mod._record_jev_usage(conn, SimpleNamespace(last_usage={'cost': None, 'input_tokens': 100, 'output_tokens': 10}), c.Decision(), '1')
    spend = db.jev_spend(conn)
    assert spend['calls'] == 1 and spend['input_tokens'] == 100
    assert spend['unknown_cost_calls'] == 1


def test_topic_context_parent_and_watermark_are_scoped(system):
    home, cfg, mod, conn = system
    add(conn, '1', 'other chat parent', chat='other', name='Wrong room')
    add(conn, '1', 'correct parent', topic='a', name='Correct room')
    add(conn, '2', 'Current question', topic='a', reply='1')
    add(conn, '3', 'UNRELATED_TOPIC_SECRET', topic='b')
    token = mod._SCAN_TOPIC.set('a')
    try:
        recent = mod._recent_pairs(conn, CHAT, 30)
        assert not any('UNRELATED' in row[1] for row in recent)
        assert next(row for row in recent if row[1] == 'Current question')[2] == 'Correct room'
        first_key = mod._watermark_key(CHAT)
        db.set_meta(conn, first_key, NOW.isoformat())
    finally:
        mod._SCAN_TOPIC.reset(token)
    token = mod._SCAN_TOPIC.set('b')
    try:
        assert mod._watermark_key(CHAT) != first_key
        assert mod._candidate(conn, CHAT).message_id == '3'
    finally:
        mod._SCAN_TOPIC.reset(token)


def test_other_bot_does_not_steal_companion_identity_or_clock(system):
    home, cfg, mod, conn = system
    add(conn, 'own', 'Own reply', peer='luna', bot=True, timestamp=NOW-timedelta(minutes=5))
    add(conn, '1', 'Other bot reply', bot=True)
    add(conn, '2', reply='1')
    assert mod._candidate(conn, CHAT).message_id == '2'
    _, minutes = mod._since_luna(conn, CHAT, now=NOW)
    assert minutes == 5


def test_disable_or_edit_during_judgment_prevents_injection(system, monkeypatch):
    home, cfg, mod, conn = system
    add(conn)
    db.set_meta(conn, mod._watermark_key(CHAT), (NOW-timedelta(seconds=10)).isoformat())
    injected = []
    mod._CTX = SimpleNamespace(inject_message=lambda *a, **kw: injected.append(True))
    def ask(*args):
        cfg['luna']['ambient']['enabled'] = False
        (home/'config.yaml').write_text(json.dumps(cfg))
        return valid_answers()
    monkeypatch.setattr(mod, '_jev_client', lambda: SimpleNamespace(ask=ask))
    mod.poll_once()
    assert not injected


def test_receipt_alone_records_delivery_and_history_exactly_once(system):
    home, cfg, mod, conn = system
    add(conn)
    candidate = mod._candidate(conn, CHAT)
    decision = mod._attribute_candidate(c.Decision(action='message', target_message_id='1'), candidate)
    receipts = []
    mod._CTX = SimpleNamespace(inject_message=lambda *a, **kw: receipts.append(kw['luna_delivery']) or True)
    assert mod._inject('synthetic brief', CHAT, decision)
    mod._on_post_llm_call(user_message='synthetic brief', assistant_response='Synthetic output')
    assert conn.execute('SELECT COUNT(*) FROM wakes').fetchone()[0] == 0
    receipts[0]['complete']('delivered', 'Synthetic output', 'sent-1')
    receipts[0]['complete']('delivered', 'Synthetic output', 'sent-1')
    assert conn.execute('SELECT COUNT(*) FROM wakes').fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM messages WHERE message_id='sent-1'").fetchone()[0] == 1


@pytest.mark.parametrize('status', ['not_admitted', 'no_reply', 'delivery_failed', 'cancelled'])
def test_failed_or_silent_receipt_does_not_claim_speech(system, status):
    home, cfg, mod, conn = system
    add(conn)
    decision = mod._attribute_candidate(c.Decision(action='message', target_message_id='1'), mod._candidate(conn, CHAT))
    receipts = []
    mod._CTX = SimpleNamespace(inject_message=lambda *a, **kw: receipts.append(kw['luna_delivery']) or True)
    assert mod._inject('synthetic brief', CHAT, decision)
    receipts[0]['complete'](status)
    assert conn.execute('SELECT COUNT(*) FROM wakes').fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM messages WHERE peer_id='luna'").fetchone()[0] == 0
    assert not mod._inject('synthetic brief', CHAT, decision)  # no duplicate generation for the same intent


def test_receipt_lease_checks_off_edit_and_original_age(system):
    home, cfg, mod, conn = system
    add(conn)
    decision = mod._attribute_candidate(c.Decision(action='message', target_message_id='1'), mod._candidate(conn, CHAT))
    assert mod._still_relevant(decision)
    conn.execute("UPDATE messages SET content='Edited question'")
    conn.commit()
    assert not mod._still_relevant(decision)
    decision.source_timestamp = (NOW-timedelta(minutes=10)).isoformat()
    assert not mod._still_relevant(decision)


def test_multiple_watched_groups_and_topics_round_robin(system, monkeypatch):
    home, cfg, mod, conn = system
    second = '-1000000000000-other'
    cfg['telegram']['group_allowed_chats'].append(second)
    cfg['luna']['ambient']['watched_chats'] = [CHAT, second]
    (home/'config.yaml').write_text(json.dumps(cfg))
    add(conn, '1', topic='a'); add(conn, '2', topic='b'); add(conn, '1', chat=second)
    scopes = []
    monkeypatch.setattr(mod, '_poll_scope', lambda *a: scopes.append((mod._ACTIVE_CHAT.get(), mod._SCAN_TOPIC.get())))
    for _ in range(3):
        mod.poll_once()
    assert set(scopes) == {(CHAT, 'a'), (CHAT, 'b'), (second, '')}


def test_worker_requires_owner_and_stops_on_unload(system, monkeypatch):
    home, cfg, mod, conn = system
    callbacks, hooks = [], {}
    ctx = SimpleNamespace(on_unload=callbacks.append, register_hook=lambda name, callback: hooks.update({name: callback}))
    monkeypatch.setattr(mod, 'poll_once', lambda *a: None)
    mod.register(ctx)
    assert mod._THREAD is None  # importing gateway code is not ownership
    hooks['gateway_ready'](gateway=SimpleNamespace(_running=True))
    assert mod._THREAD.is_alive()
    callbacks[0]()
    assert not mod._THREAD.is_alive()


def test_setup_auth_failure_and_changed_config_are_not_ready(system, monkeypatch):
    from luna_cli import onboarding
    home, cfg, mod, conn = system
    monkeypatch.setattr(onboarding, '_config', lambda: cfg)
    monkeypatch.setattr(JevClient, 'ask', lambda *a: (_ for _ in ()).throw(JevError('HTTP 401', status=401)))
    report = onboarding.run_wake_test(live=True)
    assert not report['ok']
    assert onboarding.check_wake_test()['status'] == 'todo'
    monkeypatch.setattr(JevClient, 'ask', lambda self, state, questions: valid_answers(questions))
    assert onboarding.run_wake_test(live=True)['ok']
    assert onboarding.check_wake_test()['status'] == 'done'
    cfg['luna']['ambient']['jev']['providers']['local']['model'] = 'changed'
    assert onboarding.check_wake_test()['status'] == 'todo'


def test_offline_replay_uses_scoped_scores_never_history_or_network(system):
    from luna_core.jev_replay import replay
    home, cfg, mod, conn = system
    add(conn, text='PRIVATE_TRANSCRIPT_NOT_FOR_REPLAY')
    candidate = mod._candidate(conn, CHAT)
    client = SimpleNamespace(last_answers=valid_answers(), validated=True)
    mod._record_judgment(conn, client, c.Decision(), candidate, NOW)
    raw = conn.execute('SELECT * FROM ambient_judgments').fetchone()
    assert 'PRIVATE_TRANSCRIPT' not in str(dict(raw))
    result = replay(home/'luna-state.db', cfg)
    assert result['ok'] and result['network_calls'] == 0
    assert len(result['report']) == 1 and result['report'][0]['chat_id'] == CHAT


def test_log_only_guard_verdict_cannot_establish_healthy(system):
    from luna_cli import api_models
    home, cfg, mod, conn = system
    (home/'agent.log').write_text('[luna-ambient] verdict=silent reason=judgement resource guard\n')
    assert api_models._jev_health()['status'] != 'healthy'


def test_stale_internal_target_is_rejected_using_indexed_source_time(system):
    from dataclasses import replace
    from luna_core.room_dispatch import Coordinator, Policy
    fixture = load('luna/tests/component/test_room_dispatch.py', 'dispatch_fixture_regression')
    home, cfg, mod, conn = system
    add(conn, '101', timestamp=NOW-timedelta(minutes=10))
    async def run():
        adapter = fixture.Adapter(home)
        coordinator = Coordinator(adapter, home, replace(Policy(), settle_seconds=0),
                                  wall_clock=lambda: NOW.timestamp(), known=lambda *a: False)
        value = fixture.event(1, chat=CHAT, user='synthetic-user')
        value.internal = True
        await coordinator.submit(value)
        await asyncio.wait_for(fixture.idle(coordinator), 3)
        assert not adapter.sent and not value._gateway_accepted
    asyncio.run(run())


def test_new_route_does_not_inherit_previous_route_cooldown(system):
    home, cfg, mod, _ = system
    first = mod._jev_client()
    mod._pause_jev(600, 'old route exhausted')
    assert mod._jev_paused()
    cfg['luna']['ambient']['jev']['providers']['local']['model'] = 'another-synthetic-model'
    (home / 'config.yaml').write_text(json.dumps(cfg))
    assert mod._jev_client() is not first
    assert not mod._jev_paused()


def test_persona_changes_invalidate_pending_judgments(system):
    home, cfg, mod, _ = system
    before = mod._intent_revision()
    (home / 'SOUL.md').write_text('# Mira\nUpdated preferences for joining a conversation.\n')
    assert mod._intent_revision() != before
    cfg['luna']['character']['name'] = 'Nora'
    (home / 'config.yaml').write_text(json.dumps(cfg))
    assert mod._luna_section()['character']['name'] == 'Nora'
    assert all('Luna' not in str(question) for question in c.build_questions())


def test_offline_replay_applies_saved_custom_condition_answers(system):
    from dataclasses import asdict
    from luna_core.behaviour_policy import apply_policy, validate_policy
    from luna_core.jev_replay import replay
    home, cfg, mod, conn = system
    configured = {'questions': {}, 'rules': [{'id': 'permission', 'name': 'Room permission', 'instructions': 'May the companion join?',
                  'action': 'both', 'threshold': 0.8, 'enabled': True}]}
    cfg['luna']['ambient']['decision'] = configured
    questions = apply_policy(c.build_questions(), validate_policy(configured, c.build_questions()))
    answers = valid_answers(questions)
    conn.execute("INSERT INTO ambient_judgments(chat_id,thread_id,message_id,created_at,answers,original_action,candidate_text,revision) VALUES (?,?,?,?,?,?,?,?)",
                 (CHAT, '', 'replay-condition', NOW.isoformat(), json.dumps({key: asdict(value) for key, value in answers.items()}), 'message', '', 'fixture'))
    conn.commit()
    result = replay(home / 'luna-state.db', cfg)
    assert result['network_calls'] == 0
    assert result['report'][0]['action'] == 'silent'
    assert result['report'][0]['reason'] == 'custom condition: Room permission'
