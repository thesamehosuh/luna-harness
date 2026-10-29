"""File scopes, disclosure snapshots, profile connections and maintenance regressions."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from luna_core import db, people
from luna_core.group_memory import GroupMemoryStore, scope, owner_dm
from luna_core.identity import IdentityRegistry
from luna_core.room import record_inbound

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def system(tmp_path, monkeypatch):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setenv('LUNA_HOME', str(tmp_path))
    token = set_hermes_home_override(tmp_path)
    config = {'memory': {'memory_enabled': True, 'user_profile_enabled': True, 'write_approval': False,
                        'memory_char_limit': 2200, 'user_char_limit': 1375, 'nudge_interval': 4},
              'telegram': {'allow_admin_from': ['1'], 'group_allowed_chats': ['-101', '-102']},
              'luna': {'setup': {'memory': 'enabled'}}}
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    (tmp_path / 'memories').mkdir()
    (tmp_path / 'memories/USER.md').write_text('Owner private profile')
    (tmp_path / 'memories/MEMORY.md').write_text('Owner private notes')
    conn = db.connect(tmp_path / 'luna-state.db'); db.init_db(conn)
    registry = IdentityRegistry(conn)
    for uid in ['1', '2']:
        registry.upsert_auto('telegram', uid, display_name='Observed ' + uid)
        for chat in ['-101', '-102']:
            record_inbound(conn, chat_id=chat, message_id=uid, user_id=uid, peer_id='telegram_' + uid, content='public room message')
    try:
        yield tmp_path, config, conn, registry
    finally:
        conn.close()
        reset_hermes_home_override(token)


def load_memory():
    spec = importlib.util.spec_from_file_location('memory_scope_plugin', ROOT / 'luna/plugins/luna-memory/__init__.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_group_files_maintain_without_touching_private_or_other_topics(system):
    root, config, _, _ = system
    a = GroupMemoryStore(scope('telegram', '-101'), config)
    b = GroupMemoryStore(scope('telegram', '-101', '9'), config)
    assert a.add('memory', 'Friday board games')['success']
    from tools.memory_tool import memory_tool
    from tools.skill_provenance import set_current_write_origin, reset_current_write_origin
    token = set_current_write_origin('background_review')
    try:
        result = json.loads(memory_tool(action='replace', old_text='Friday', content='Saturday board games', store=a))
    finally:
        reset_current_write_origin(token)
    assert result['success'] and not result.get('staged')
    assert 'Saturday' in a.turn_context_block()
    assert 'Saturday' not in b.turn_context_block()
    assert a.format_for_system_prompt('memory') is None
    assert (root / 'memories/MEMORY.md').read_text() == 'Owner private notes'
    assert (root / 'memories/USER.md').read_text() == 'Owner private profile'
    assert a.directory.stat().st_mode & 0o777 == 0o700


def test_dashboard_conflict_preserves_agent_notes_and_scoped_people(system):
    from luna_cli import groups
    root, config, _, registry = system
    group = next(row for row in groups.bundle()['groups'] if row['chat_id'] == '-101')
    before = groups.bundle(group['id'])['group']['notes']['revision']
    store = GroupMemoryStore(scope('telegram', '-101'), config)
    store.add('memory', 'A fact saved during conversation')
    with pytest.raises(groups.Conflict):
        groups.update_notes(group['id'], ['An old dashboard draft'], before)
    assert 'A fact saved' in store._path_for('memory').read_text()
    groups.update_person(group['id'], '2', {'display_name': 'Room nickname', 'role': ''})
    scoped = next(row for row in groups.people_bundle()['people'] if row['user_id'] == '2')
    assert scoped['shared']['display_name'] == 'Observed 2'
    assert next(row for row in scoped['groups'] if row['chat_id'] == '-101')['entry']['display_name'] == 'Room nickname'
    assert next(row for row in scoped['groups'] if row['chat_id'] == '-102')['entry']['display_name'] == 'Observed 2'
    assert people.read()[('telegram', '2', 'group', '-101')]['role'] == ''
    groups.update_person(group['id'], '2', {}, inherit=True)
    assert ('telegram', '2', 'group', '-101') not in people.read()


def disclosure_context(monkeypatch, config, *, direct=False):
    from luna_core import private_memory
    from gateway import session_context
    ctx = {'platform': 'telegram', 'chat_type': 'dm' if direct else 'group', 'chat_id': '1' if direct else '-101',
           'thread_id': '', 'user_id': '1' if direct else '2'}
    monkeypatch.setattr(private_memory, 'transport_context', lambda: ctx)
    monkeypatch.setattr(private_memory.config_read, 'load_config', lambda: config)
    monkeypatch.setattr(session_context, 'get_session_env', lambda key, default=None: '42' if key == 'HERMES_SESSION_MESSAGE_ID' else default)
    return private_memory


@pytest.mark.parametrize('choice,resolved', [('deny', True), ('always', True), (None, False), ('once', True)])
def test_private_read_requires_exact_once_approval_and_returns_approved_snapshot(system, monkeypatch, choice, resolved):
    root, config, _, _ = system
    private = disclosure_context(monkeypatch, config)
    from tools import approval, approval_context, approval_gateway_wait
    monkeypatch.setattr(approval_context, 'get_current_session_key', lambda: 'group-session')
    monkeypatch.setitem(approval._gateway_notify_cbs, 'group-session', lambda data: None)
    captured = {}
    def answer(key, notify, payload):
        captured.update(payload)
        assert key.startswith('private-memory:') and key != 'group-session'
        (root / 'memories/USER.md').write_text('A different later private profile')
        return {'resolved': resolved, 'choice': choice}
    monkeypatch.setattr(approval_gateway_wait, '_await_gateway_decision', answer)
    result = json.loads(private.tool_handler({'source': 'user', 'query': ''}))
    assert captured['owner_dm_only'] and not captured['allow_permanent'] and not captured['allow_session']
    assert 'Owner private profile' in captured['command'] and '-101' in captured['command']
    if choice == 'once':
        assert result['content'] == 'Owner private profile' and result['owner_approved']
    else:
        assert not result['ok'] and 'content' not in result


def test_owner_dm_private_read_never_requests_approval(system, monkeypatch):
    _, config, _, _ = system
    private = disclosure_context(monkeypatch, config, direct=True)
    monkeypatch.setattr('tools.approval_gateway_wait._await_gateway_decision', lambda *args: pytest.fail('Owner DM reads are approval-free'))
    assert json.loads(private.tool_handler({'source': 'memory', 'query': ''}))['content'] == 'Owner private notes'
    assert owner_dm(config, 'telegram', 'dm', '1', '1')
    assert not owner_dm(config, 'telegram', 'group', '-101', '1')
    assert not owner_dm(config, 'discord', 'dm', '1', '1')
    assert not owner_dm(config, 'telegram', 'dm', '2', '2')


def test_group_lookup_in_owner_dm_is_explicit_and_works_without_honcho(system, monkeypatch):
    from luna_core import group_memory
    root, config, _, _ = system
    GroupMemoryStore(scope('telegram', '-101'), config).add('memory', 'Public group plan')
    monkeypatch.setattr(group_memory, 'transport_context', lambda: dict(platform='telegram', chat_type='dm', chat_id='1', thread_id='', user_id='1'))
    listing = json.loads(group_memory.tool_handler({'action': 'list'}))
    assert {item['chat_id'] for item in listing['groups']} == {'-101', '-102'}
    result = json.loads(group_memory.tool_handler({'action': 'read', 'chat_id': '-101'}))
    assert result['content'] == 'Public group plan'
    assert (root / 'memories/MEMORY.md').read_text() == 'Owner private notes'


def test_named_profile_aliases_match_selected_client_and_cache_signature_changes(system, monkeypatch):
    root, _, _, registry = system
    from luna_core.peers import update_honcho_aliases
    from plugins.memory.honcho import client
    monkeypatch.setattr(client, 'resolve_active_host', lambda: 'hermes_other')
    raw = {'baseUrl': 'http://127.0.0.1:9', 'hosts': {'hermes': {'workspace': 'isolated-fixture', 'enabled': True,
           'runtimePeerPrefix': 'telegram_', 'aiPeer': 'assistant-fixture'}}}
    (root / 'honcho.json').write_text(json.dumps(raw))
    update_honcho_aliases(root / 'honcho.json', registry)
    parsed = client.HonchoClientConfig.from_global_config()
    assert parsed.workspace_id == 'isolated-fixture'
    assert parsed.user_peer_aliases['2'] == registry.get('telegram', '2').peer_id
    assert parsed.runtime_peer_prefix == 'telegram_' and parsed.ai_peer == 'assistant-fixture'
    provider = load_memory().LunaMemoryProvider()
    before = provider.identity_signature()
    raw = json.loads((root / 'honcho.json').read_text()); raw['hosts']['hermes_other']['contextCadence'] = 7
    (root / 'honcho.json').write_text(json.dumps(raw))
    assert provider.identity_signature() != before


def test_clone_disconnects_live_memory_but_preserves_note_choices(system):
    from luna_core.profile_memory import detach_clone
    root, config, _, _ = system
    staging, destination = root / 'staging', root / 'profiles/other'
    staging.mkdir(); (staging / 'config.yaml').write_text(yaml.safe_dump({**config, 'honcho': {'workspace': 'source', 'baseUrl': 'http://127.0.0.1:12345'}}, sort_keys=False))
    (staging / '.env').write_text('LUNA_HONCHO_WORKSPACE=source\nLUNA_HONCHO_BASE_URL=http://127.0.0.1:12345\nMODEL_KEY=synthetic\n')
    (staging / 'honcho').mkdir(); (staging / 'honcho/.bridge-ready.json').write_text('{}')
    detach_clone(staging, destination)
    copied = yaml.safe_load((staging / 'config.yaml').read_text())
    assert copied['honcho']['workspace'] != 'source'
    assert copied['luna']['setup']['memory'] == 'pending'
    assert copied['luna']['setup']['jev'] == 'pending'
    assert not copied['luna']['ambient']['enabled'] and copied['luna']['ambient']['watched_chats'] == []
    assert copied['memory']['memory_enabled'] and copied['memory']['user_profile_enabled']
    assert not (staging / 'honcho').exists()
    assert (staging / '.env').read_text() == 'MODEL_KEY=synthetic\n'


def test_honcho_skip_never_changes_file_flags(system, monkeypatch):
    from luna_cli import onboarding
    root, _, _, _ = system
    monkeypatch.setattr(onboarding, 'step_report', lambda: {})
    monkeypatch.setattr('luna_core.managed_memory.disable', lambda: None)
    onboarding.set_choice('honcho', 'skipped')
    saved = yaml.safe_load((root / 'config.yaml').read_text())
    assert saved['memory']['memory_enabled'] and saved['memory']['user_profile_enabled']
    assert saved['luna']['setup']['memory'] == 'skipped'


def test_people_only_group_still_gets_periodic_maintenance(system):
    _, config, _, _ = system
    config['memory']['memory_enabled'] = False
    from luna_core.group_memory import configure_agent
    from agent.turn_context import _tick_memory_nudge
    agent = SimpleNamespace(platform='telegram', _chat_id='-101', _thread_id='', enabled_toolsets=['people'],
                            disabled_toolsets=[], valid_tool_names={'tool_search', 'tool_call'}, _turns_since_memory=0)
    configure_agent(agent, config, False)
    assert not agent._memory_store.memory_enabled and agent._memory_store.people_enabled
    assert [_tick_memory_nudge(agent) for _ in range(4)] == [False, False, False, True]


def test_honcho_tools_are_forwarded_and_cached_provider_obeys_off_switch(system, monkeypatch):
    provider = load_memory().LunaMemoryProvider()
    provider._backend = SimpleNamespace(get_tool_schemas=lambda: [{'name': 'honcho_search'}],
                                       handle_tool_call=lambda name, args, **kwargs: 'a saved answer',
                                       prefetch=lambda *args, **kwargs: pytest.fail('Disabled Honcho must not query'))
    assert provider.get_tool_schemas() == [{'name': 'honcho_search'}]
    assert provider.handle_tool_call('honcho_search', {}) == 'a saved answer'
    root, config, _, _ = system
    config['luna']['setup']['memory'] = 'skipped'
    (root / 'config.yaml').write_text(json.dumps(config))
    assert provider.get_tool_schemas() == []
    assert provider.prefetch('Who is this person?') == ''


def test_public_recall_obeys_tools_mode_cadence_and_first_turn(system, monkeypatch):
    from luna_core.room_memory import RoomMemory
    from plugins.memory.honcho.client import HonchoClientConfig
    config = SimpleNamespace(enabled=True, recall_mode='context', context_cadence=3, injection_frequency='every-turn')
    monkeypatch.setattr(HonchoClientConfig, 'from_global_config', lambda: config)
    memory = RoomMemory('public-room', 'telegram_2', 2000)
    calls = []
    monkeypatch.setattr(memory, 'recall', lambda query: calls.append(query) or 'public facts')
    memory.on_turn_start(1, 'first'); assert memory.prefetch('first') == 'public facts'
    memory.on_turn_start(2, 'next'); assert memory.prefetch('next') == 'public facts'
    assert calls == ['first']
    memory.peer_id = 'telegram_1'
    assert memory.prefetch('new sender') == 'public facts' and calls[-1] == 'new sender'
    config.recall_mode = 'tools'
    assert memory.prefetch('explicit tool required') == ''
    config.recall_mode, config.injection_frequency = 'context', 'first-turn'
    assert memory.prefetch('later turn') == ''


@pytest.mark.parametrize('native_success', [True, False])
def test_private_preview_and_fallback_can_only_be_delivered_to_owner_dm(system, native_success):
    import asyncio
    from dataclasses import dataclass
    from gateway.run_turn_runner import TurnRunner
    from gateway.platforms.base import SendResult
    _, config, _, _ = system
    deliveries = []
    class Adapter:
        def pause_typing_for_chat(self, chat):
            assert chat == '1'
        async def send_exec_approval(self, **kwargs):
            deliveries.append(('card', kwargs))
            return SendResult(success=native_success, message_id='preview' if native_success else None)
        async def send(self, chat_id, message, **kwargs):
            deliveries.append(('text', {'chat_id': chat_id, 'message': message, **kwargs}))
            return SendResult(success=True, message_id='fallback')
    @dataclass
    class Context:
        source: object
        user_config: dict
        _status_adapter: object
        _status_chat_id: str
        _status_thread_metadata: dict
        session_key: str
    runner = object.__new__(TurnRunner)
    runner._ctx = Context(SimpleNamespace(platform='telegram', chat_id='-101'), config, Adapter(), '-101', {'thread_id': '99'}, 'group-session')
    class Future:
        def __init__(self, result): self.value = result
        def result(self, timeout=None): return self.value
    runner._schedule = lambda coro, label: Future(asyncio.run(coro))
    runner._close_native_stream_boundary = lambda *args: None
    runner._approval_notify_sync({'owner_dm_only': True, 'approval_session_key': 'private-memory:fixture',
                                 'preview_sanitized': True, 'command': 'Exact private excerpt',
                                 'allow_permanent': False, 'allow_session': False})
    assert deliveries and all(kwargs['chat_id'] == '1' for kind, kwargs in deliveries)
    assert all(not kwargs.get('metadata') or 'thread_id' not in kwargs['metadata'] for kind, kwargs in deliveries)
    card = deliveries[0][1]
    assert card['session_key'] == 'private-memory:fixture' and card['kind'] == 'private_memory'
    assert not card['allow_permanent'] and not card['allow_session']
    if not native_success:
        assert deliveries[-1][0] == 'text' and 'Exact private excerpt' in deliveries[-1][1]['message']


def test_gateway_identity_provider_probe_is_cached_per_profile(system, monkeypatch):
    from gateway.run_agent_cache import GatewayAgentCacheMixin
    from hermes_constants import get_hermes_home, set_hermes_home_override, reset_hermes_home_override
    from plugins import memory
    root, _, _, _ = system
    loaded = []
    def load(name, **kwargs):
        bound_home = str(get_hermes_home())
        loaded.append(bound_home)
        return SimpleNamespace(identity_signature=lambda: {'bound_home': bound_home})
    monkeypatch.setattr(memory, 'load_memory_provider', load)
    monkeypatch.setattr(GatewayAgentCacheMixin, '_MEMORY_IDENTITY_PROVIDER_MEMO', {})
    one = GatewayAgentCacheMixin._memory_provider_identity_signature('luna-memory')
    token = set_hermes_home_override(root / 'profiles/other')
    try:
        two = GatewayAgentCacheMixin._memory_provider_identity_signature('luna-memory')
    finally:
        reset_hermes_home_override(token)
    again = GatewayAgentCacheMixin._memory_provider_identity_signature('luna-memory')
    assert one != two and again == one and len(loaded) == 2


def test_public_group_history_keeps_its_legacy_identity_across_topics(system, monkeypatch):
    from luna_core.honcho import public_room_session
    monkeypatch.setenv('LUNA_CHAT_ID', '-101')
    monkeypatch.setenv('LUNA_ROOM_SESSION_KEY', 'existing-public-room')
    assert public_room_session('telegram', '-101') == 'existing-public-room'
    assert public_room_session('telegram', '-101', '9') == 'existing-public-room'
    assert public_room_session('telegram', '-102') != 'existing-public-room'


def test_new_sender_lookup_failure_does_not_erase_existing_group_summary(system):
    from luna_core.room_memory import RoomMemory
    class Session:
        def representation(self, *args, **kwargs):
            raise LookupError('This newly observed author has no remote peer yet')
        def summaries(self):
            return SimpleNamespace(long_summary=SimpleNamespace(content='The group meets Fridays for board games.'), short_summary=None)
    memory = RoomMemory('existing-public-room', 'new-transport-peer', 2000)
    memory.store._client = SimpleNamespace(session=lambda name: Session())
    assert 'board games' in memory.prefetch('What does this group do?')
    assert memory.degraded


def test_public_recall_prioritizes_derived_sender_knowledge_and_preserves_provenance(system):
    from luna_core.room_memory import RoomMemory
    calls = []
    def search(query, *, top_k, filters):
        calls.append((query, filters))
        rows = [('private-room', 'telegram_2', 'Private fact'),
                ('public-room', 'telegram_1', 'Another author fact')]
        content = ('The sender uses the nickname Rowan.' if query == 'my real name and nicknames'
                   else 'The sender maintains a Python music app.')
        rows.append(('public-room', 'telegram_2', content))
        return [SimpleNamespace(session_id=s, observed_id=p, content=text, level='deductive') for s, p, text in rows]
    session = SimpleNamespace(summaries=lambda: SimpleNamespace(
        long_summary=SimpleNamespace(content='The group plays cooperative games. ' * 300), short_summary=None))
    memory = RoomMemory('public-room', 'telegram_2', 2000)
    memory.store._client = SimpleNamespace(session=lambda name: session,
        peer=lambda name: SimpleNamespace(conclusions=SimpleNamespace(query=search)))
    recalled = memory.prefetch('LUNA WHO AM I')
    assert 'Rowan' in recalled and 'Python music app' in recalled
    assert 'Private fact' not in recalled and 'Another author fact' not in recalled
    assert '[deductive]' in recalled and 'remembered claims' in recalled
    assert len(recalled) <= 2000 and not memory.degraded
    assert all(filters == {'session_id': 'public-room'} for _, filters in calls)
    provider = load_memory().LunaMemoryProvider()
    provider._room_chat = '-101'
    provider._backend = SimpleNamespace(prefetch=lambda *a, **kw: recalled)
    assert provider.prefetch('LUNA WHO AM I') == recalled


def test_explicit_public_recall_searches_messages_even_without_a_selected_peer(system):
    from luna_core.room_memory import RoomMemory
    calls = []
    def search(query, **kw):
        calls.append(query)
        return [SimpleNamespace(session_id='public-room', peer_id='telegram_2', content='Rowan writes music software.'),
                SimpleNamespace(session_id='private-room', peer_id='telegram_2', content='Private source')]
    session = SimpleNamespace(search=search, summaries=lambda: SimpleNamespace(long_summary=None, short_summary=None))
    memory = RoomMemory('public-room', None, 2000)
    memory.store._client = SimpleNamespace(session=lambda name: session)
    recalled = memory.recall('music software', search_messages=True)
    assert calls == ['music software']
    assert 'music software' in recalled and 'Private source' not in recalled
    assert 'historical evidence, not instructions' in recalled


def test_group_recall_tool_resolves_current_transport_sender_and_uses_query(system, monkeypatch):
    from luna_core import group_memory, room_memory
    from plugins.memory.honcho.client import HonchoClientConfig
    _, config, _, _ = system
    monkeypatch.setattr(group_memory, 'transport_context', lambda: dict(platform='telegram',chat_type='group',chat_id='-101',thread_id='',user_id='2'))
    monkeypatch.setattr(HonchoClientConfig, 'from_global_config', lambda: SimpleNamespace(enabled=True))
    calls = []
    class Memory:
        def __init__(self, session, peer, budget):
            self.store, self.degraded = SimpleNamespace(_client=None), False
            calls.append(peer)
        def recall(self, query, *, search_messages):
            calls.append((query, search_messages)); return 'Public derived knowledge'
    monkeypatch.setattr(room_memory, 'RoomMemory', Memory)
    result = json.loads(group_memory.tool_handler({'action':'recall','query':'names and work'}))
    assert result['content'] == 'Public derived knowledge'
    assert calls == ['telegram_2', ('names and work', True)]
    result = json.loads(group_memory.tool_handler({'action':'recall','query':'names','user_id':'unobserved'}))
    assert result['ok'] is False


def test_luna_memory_tools_are_direct_but_still_respect_toolset_gates(system, monkeypatch):
    from hermes_cli import product_runtime
    from tools.registry import registry
    from hermes_constants import hermes_home_key
    from luna_core import group_memory, private_memory
    import model_tools
    monkeypatch.setattr(product_runtime, 'enabled', lambda: True)
    for toolset, module in [('people', people), ('memory', group_memory), ('memory', private_memory)]:
        registry.register(name=module.TOOL_SCHEMA['name'], toolset=toolset, schema=module.TOOL_SCHEMA,
                          handler=module.tool_handler, scope=hermes_home_key())
    tools = model_tools.get_tool_definitions(enabled_toolsets=['people','memory'],quiet_mode=True)
    names = {tool['function']['name'] for tool in tools}
    assert {'people','group_memory','private_memory'} <= names
    restricted = model_tools.get_tool_definitions(enabled_toolsets=['web'],quiet_mode=True)
    assert not ({'people','group_memory','private_memory'} & {t['function']['name'] for t in restricted})
    from tools.tool_search import is_deferrable_tool_name
    assert is_deferrable_tool_name('group_memory', frozenset({'group_memory'}))


def test_dashboard_note_files_edit_private_and_group_files_and_detect_model_changes(system):
    from luna_cli import note_files
    root, config, _, _ = system
    catalog = note_files.catalog()['files']
    assert {'memory','user','people'} <= {item['id'] for item in catalog}
    assert all('content' not in item and 'path' not in item for item in catalog)
    before = note_files.read('user')
    saved = note_files.save('user', 'New owner profile', before['revision'])
    assert (root/'memories/USER.md').read_text() == saved['content'] == 'New owner profile'
    with pytest.raises(note_files.Conflict):
        note_files.save('user', 'Stale draft', before['revision'])
    group = next(item for item in catalog if item['id'].startswith('group-'))
    blank = note_files.read(group['id'])
    saved = note_files.save(group['id'], 'Group public plans', blank['revision'])
    assert saved['content'] == 'Group public plans'
    assert (root/'memories/MEMORY.md').read_text() == 'Owner private notes'
    with pytest.raises(ValueError, match='within'):
        note_files.save(group['id'], 'x' * 2201, saved['revision'])
    with pytest.raises(ValueError):
        note_files.read('../config.yaml')


def test_dashboard_people_file_edit_preserves_scopes_and_validates_transport_ids(system):
    from luna_cli import note_files
    root, _, _, registry = system
    people.refresh(registry)
    before = note_files.read('people')
    content = before['content'] + '\n## telegram / 2 / group / -101\n- Name: Rowan\n- Aliases: ["Ro"]\n- Role: Board game host\n'
    saved = note_files.save('people', content, before['revision'])
    assert people.read()[('telegram','2','group','-101')]['display_name'] == 'Rowan'
    assert 'Rowan' in people.context(registry,'telegram',['2'],chat_type='group',chat_id='-101')
    assert 'Rowan' not in people.context(registry,'telegram',['2'],chat_type='group',chat_id='-102')
    for invalid in [content + '\n## telegram / 999\n- Name: Invented\n',
                    content.replace('Board game host','x'*121),
                    content.replace('["Ro"]','["a","b","c","d","e"]'),
                    content + '\n## telegram / 2 / group / -101\n- Name: Duplicate\n',
                    content.replace('- Role: Board game host','- Biography: Unexpected')]:
        with pytest.raises(ValueError):
            note_files.save('people', invalid, saved['revision'])
    assert (root/'PEOPLE.md').read_text() == content


def test_dashboard_note_file_conflict_covers_background_people_edits_and_symlinks(system):
    from luna_cli import note_files
    from luna_core.settings import _replace
    root, _, _, registry = system
    people.refresh(registry)
    before = note_files.read('people')
    _replace(root/'PEOPLE.md', before['content']+'\n')
    with pytest.raises(note_files.Conflict):
        note_files.save('people',before['content'],before['revision'])
    (root/'memories/USER.md').unlink()
    (root/'memories/USER.md').symlink_to(root/'config.yaml')
    with pytest.raises(ValueError,match='linked'):
        note_files.read('user')


def test_disabled_note_use_does_not_prevent_manual_dashboard_edits(system):
    from luna_cli import note_files
    root, config, _, _ = system
    config['memory']['memory_enabled'] = False
    (root/'config.yaml').write_text(yaml.safe_dump(config))
    before = note_files.read('memory')
    assert not before['enabled']
    assert note_files.save('memory','A manually maintained note',before['revision'])['content'] == 'A manually maintained note'


def test_note_file_revisions_are_bound_to_the_file_and_profile(system):
    from luna_cli import note_files
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    root, _, _, _ = system
    (root/'memories/MEMORY.md').write_text('Same content')
    (root/'memories/USER.md').write_text('Same content')
    original = note_files.read('memory')
    assert original['revision'] != note_files.read('user')['revision']
    other = root/'profiles/other'
    (other/'memories').mkdir(parents=True)
    (other/'memories/MEMORY.md').write_text('Same content')
    (other/'config.yaml').write_text('memory: {}\nluna: {}\n')
    token = set_hermes_home_override(other)
    try:
        assert note_files.read('memory')['revision'] != original['revision']
        with pytest.raises(note_files.Conflict):
            note_files.save('memory','Wrong profile draft',original['revision'])
    finally:
        reset_hermes_home_override(token)
    assert (root/'memories/MEMORY.md').read_text() == 'Same content'
