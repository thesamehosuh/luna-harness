"""Integration regressions from the release audit; synthetic homes and local fakes only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from luna_core import db, settings
from luna_cli import behaviour, character, web_routers


@pytest.fixture
def homes(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setenv('LUNA_HOME', str(tmp_path))
    for path, name in [(tmp_path, 'Primary'), (tmp_path / 'profiles/second', 'Second')]:
        path.mkdir(parents=True, exist_ok=True)
        (path / 'SOUL.md').write_text(f'# {name}\n\nA synthetic companion.\n')
        (path / 'config.yaml').write_text('model:\n  default: original\nluna:\n  ambient:\n    dry_run: true\n')
    from agent.secret_scope import is_multiplex_active, set_multiplex_active
    previous = is_multiplex_active()
    yield tmp_path
    set_multiplex_active(previous)


@pytest.fixture
def client(homes):
    app = FastAPI()
    app.include_router(web_routers.router)
    app.dependency_overrides[web_routers._require_token] = lambda: None
    return TestClient(app)


def test_secondary_profile_does_not_edit_primary(homes, client, monkeypatch):
    # Keep the test's profile resolver independent of the launch process's global home.
    import hermes_cli.web_server_profiles as profiles
    monkeypatch.setattr(profiles, '_resolve_profile_dir', lambda _: homes / 'profiles/second')
    read = client.get('/api/luna/character?profile=second')
    assert read.status_code == 200, read.text
    assert read.json()['soul']['title'] == 'Second'
    response = client.put('/api/luna/character?profile=second', json={'soul_text': '# Edited\n'})
    assert response.status_code == 200, response.text
    assert (homes / 'SOUL.md').read_text().startswith('# Primary')
    assert (homes / 'profiles/second/SOUL.md').read_text().startswith('# Edited')


def test_character_invalid_tail_rolls_back_entire_request(homes, client):
    before = (homes / 'SOUL.md').read_text()
    result = client.put('/api/luna/character', json={'soul_text': '# Changed\n', 'output': {'max_lines': -1}})
    assert result.status_code == 400
    assert (homes / 'SOUL.md').read_text() == before


def test_budget_invalid_field_cannot_enable_wakes(homes):
    before = (homes / 'config.yaml').read_text()
    result = behaviour.write_behaviour({'dry_run': False, 'budget': {'message_max_per_day': -1}})
    assert not any(row['ok'] for row in result['results'].values())
    assert (homes / 'config.yaml').read_text() == before
    result = behaviour.write_behaviour({'dry_run': False, 'budget': {'message_max_per_day': None}})
    assert all(row['ok'] for row in result['results'].values())
    assert result['behaviour']['budget']['message_max_per_day'] is None


def test_revision_rejects_stale_save(homes, client):
    revision = client.get('/api/luna/character').json()['revision']
    assert client.put('/api/luna/character', headers={'If-Match': revision}, json={'soul_text': '# First\n'}).status_code == 200
    assert client.put('/api/luna/character', headers={'If-Match': revision}, json={'soul_text': '# Stale\n'}).status_code == 409
    assert (homes / 'SOUL.md').read_text().startswith('# First')


def test_interrupted_settings_commit_recovers_before_next_write(homes, monkeypatch):
    before = (homes / 'SOUL.md').read_text()
    real = settings._replace
    def failed(path, content):
        if path.name == 'config.yaml':
            raise OSError('synthetic publication failure')
        return real(path, content)
    # A failure during publication rolls SOUL back; journal is retained if recovery also fails.
    with monkeypatch.context() as patch:
        patch.setattr(settings, '_replace', failed)
        with pytest.raises(OSError):
            with settings.transaction():
                settings.write(homes / 'SOUL.md', '# Interrupted\n')
                settings.write(homes / 'config.yaml', 'new: true\n')
    with settings.transaction():
        assert character.read_soul()['raw'] == before
    assert (homes / 'SOUL.md').read_text() == before


def test_identity_null_clears_and_omission_preserves(homes, client):
    assert client.post('/api/luna/identity', json={'user_id': 'synthetic', 'pronouns': 'they', 'role': 'friend'}).status_code == 200
    response = client.post('/api/luna/identity', json={'user_id': 'synthetic', 'pronouns': None})
    assert response.status_code == 200, response.text
    assert response.json()['identity']['pronouns'] is None
    assert response.json()['identity']['role'] == 'friend'


def test_room_backlog_drains_and_lookup_failure_never_duplicates(tmp_path):
    from luna_core.honcho import HonchoStore, backfill_room, outbox_status
    conn = db.connect(tmp_path / 'index.db')
    db.init_db(conn)
    for index in range(60):
        conn.execute('INSERT INTO messages(message_id,chat_id,peer_id,content,timestamp) VALUES (?,?,?,?,?)', (str(index), 'room', 'synthetic', 'public', f'2026-01-01T00:00:{index:02d}+00:00'))
    conn.commit()
    class Remote:
        def __init__(self): self.rows = []; self.fail = False
        def session(self, *_): return self
        def messages(self):
            if self.fail: raise OSError('offline')
            return self.rows
    remote = Remote()
    store = HonchoStore(client=remote)
    store.add_message = lambda *args, metadata=None, **kw: remote.rows.append(SimpleNamespace(metadata=metadata))
    assert backfill_room(store, conn, chat_id='room', room_session='room', limit=50).written == 50
    assert backfill_room(store, conn, chat_id='room', room_session='room', limit=50).written == 10
    assert outbox_status(conn)['pending'] == 0
    remote.fail = True
    assert backfill_room(store, conn, chat_id='room', room_session='room', limit=50).written == 0
    assert len(remote.rows) == 60
    conn.close()


def test_unconfirmed_send_is_reconciled_after_restart(tmp_path):
    from luna_core.honcho import HonchoStore, backfill_room, outbox_status
    path = tmp_path / 'index.db'
    conn = db.connect(path); db.init_db(conn)
    conn.execute("INSERT INTO messages(message_id,chat_id,peer_id,content) VALUES ('1','r','p','public')");conn.commit()
    remote = SimpleNamespace(rows=[])
    remote.session = lambda *_: remote
    remote.messages = lambda: remote.rows
    store = HonchoStore(client=remote)
    def accepted_then_timeout(*args, metadata=None, **kwargs):
        remote.rows.append(SimpleNamespace(metadata=metadata))
        raise TimeoutError()
    store.add_message = accepted_then_timeout
    assert backfill_room(store, conn, chat_id='r', room_session='r').written == 0
    assert outbox_status(conn)['uncertain'] == 1
    conn.close();conn = db.connect(path)
    assert backfill_room(store, conn, chat_id='r', room_session='r').skipped == 1
    assert len(remote.rows) == 1
    assert outbox_status(conn)['pending'] == 0
    conn.close()


def test_engine_writer_and_companion_patch_serialize(homes, monkeypatch):
    from hermes_cli import config
    from luna_core import configedit
    entered, resume = threading.Event(), threading.Event()
    real = configedit.write_config_value
    def paused(*args, **kwargs):
        entered.set()
        assert resume.wait(5)
        return real(*args, **kwargs)
    monkeypatch.setattr(configedit, 'write_config_value', paused)
    def engine_save():
        with config._CONFIG_LOCK:
            value = config.read_user_config_raw()
            value['model']['default'] = 'new-engine-model'
            config.save_config(value)
    with ThreadPoolExecutor(max_workers=2) as pool:
        companion = pool.submit(behaviour.write_behaviour, {'dry_run': False})
        assert entered.wait(5)
        engine = pool.submit(engine_save)
        assert not engine.done()
        resume.set()
        companion.result(timeout=5);engine.result(timeout=5)
    after = config.read_user_config_raw()
    assert after['model']['default'] == 'new-engine-model'
    assert after['luna']['ambient']['dry_run'] is False


def test_real_backend_lifecycle_and_alias_invalidation(homes):
    import importlib.util
    import json
    from plugins.memory.honcho import HonchoMemoryProvider
    path = Path(__file__).resolve().parents[2] / 'plugins/luna-memory/__init__.py'
    spec = importlib.util.spec_from_file_location('audit_memory', path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    provider = module.LunaMemoryProvider()
    backend = HonchoMemoryProvider()
    provider._backend = backend
    provider.on_turn_start(8, 'synthetic query', author_id='transport-1', author_name='Synthetic')
    assert backend._turn_count == 8 and backend._turn_author['id'] == 'transport-1'
    calls = []
    backend.queue_prefetch = lambda query, **kw: calls.append((query, kw))
    provider.queue_prefetch('refresh', session_id='session')
    assert calls == [('refresh', {'session_id': 'session'})]
    (homes / 'honcho.json').write_text(json.dumps({'userPeerAliases': {'one': 'first'}}))
    before = provider.identity_signature()
    (homes / 'honcho.json').write_text(json.dumps({'userPeerAliases': {'one': 'second-changed'}}))
    assert provider.identity_signature() != before
    provider.shutdown()


def test_group_capabilities_and_public_memory(homes):
    from luna_core.surface_policy import toolsets
    source = SimpleNamespace(chat_type='group', user_id='owner')
    config = {'luna': {}, 'telegram': {'allow_admin_from': ['owner']}}
    assert toolsets(config, source, ['web', 'terminal', 'memory', 'file']) == ['web']
    source.chat_type = 'dm'
    assert toolsets(config, source, ['web', 'terminal']) == ['web', 'terminal']
    source.user_id = 'stranger'
    assert toolsets(config, source, ['web', 'terminal']) == ['web']
    config['luna']['access'] = {'group_host_access': True}
    source.chat_type = 'group'
    assert toolsets(config, source, ['terminal']) == ['terminal']


def test_language_and_group_size_follow_configuration(homes):
    from luna_core.text import shape_group_reply
    character.write_output_limits({'language': 'auto', 'style_filter': False, 'max_chars': 80})
    assert 'سلام' in shape_group_reply('سلام دوست من')
    assert len(shape_group_reply('word ' * 1000).encode('utf-16-le')) // 2 <= 80
    character.write_output_limits({'language': 'english'})
    assert 'سلام' not in shape_group_reply('hello سلام')


def test_native_retention_skips_active_worker_then_removes_raw_stores(homes):
    from datetime import datetime, timezone
    import os
    from luna_core.native_resources import idle
    from luna_core.retention import prune_native
    root = homes / 'opencode';session = root / 'sessions/synthetic'
    session.mkdir(parents=True)
    (session / '.created').write_text('')
    (session / 'native.sqlite').write_text('synthetic raw bytes')
    (root / 'attachments').mkdir()
    attachment = root / 'attachments/image.png';attachment.write_bytes(b'synthetic')
    for path in [session / '.created', attachment]: os.utime(path, (1, 1))
    lease = idle(root, 'synthetic')
    result = prune_native(homes, days=1, now=datetime.now(timezone.utc))
    assert result['active_skipped'] == 1 and session.exists()
    assert not attachment.exists()
    lease.close()
    assert prune_native(homes, days=1)['sessions'] == 1
    assert not session.exists()


def test_backup_and_restore_committed_profile_wal(homes, monkeypatch):
    from luna_core import data_ops
    monkeypatch.setattr(data_ops, 'require_stopped', lambda: None)
    child = homes / 'profiles/second/history.db'
    conn = sqlite3.connect(child)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE synthetic (value TEXT)')
    conn.execute("INSERT INTO synthetic VALUES ('committed-in-wal')");conn.commit()
    snapshot = data_ops.backup()
    conn.execute('DELETE FROM synthetic');conn.commit();conn.close()
    (homes / 'SOUL.md').write_text('# Changed after backup\n')
    result = data_ops.restore(snapshot['name'])
    assert result['ok'] and result['safety_backup'] != snapshot['name']
    assert (homes / 'SOUL.md').read_text().startswith('# Primary')
    with sqlite3.connect(child) as restored:
        assert restored.execute('SELECT value FROM synthetic').fetchone()[0] == 'committed-in-wal'


def test_failed_restore_publication_recovers_all_local_files(homes, monkeypatch):
    from luna_core import data_ops
    monkeypatch.setattr(data_ops, 'require_stopped', lambda: None)
    snapshot = data_ops.backup()
    (homes / 'SOUL.md').write_text('# Current character\n')
    (homes / 'config.yaml').write_text('current: true\n')
    real = data_ops.os.replace
    failed = False
    def replace(source, target):
        nonlocal failed
        if Path(source).parent.name == 'incoming' and Path(source).name == 'SOUL.md' and not failed:
            failed = True
            raise OSError('synthetic local restore failure')
        return real(source, target)
    monkeypatch.setattr(data_ops.os, 'replace', replace)
    with pytest.raises(OSError, match='synthetic local restore failure'):
        data_ops.restore(snapshot['name'])
    assert (homes / 'SOUL.md').read_text() == '# Current character\n'
    assert (homes / 'config.yaml').read_text() == 'current: true\n'


def test_primary_worker_keeps_scope_after_multiplexing_is_enabled(homes, monkeypatch):
    from luna_core.runtime import worker_context, home, getenv
    from agent.secret_scope import set_multiplex_active, set_secret_scope, reset_secret_scope
    import hermes_constants
    monkeypatch.setattr(hermes_constants, 'get_process_hermes_home', lambda: homes)
    monkeypatch.setenv('SYNTHETIC_COMPANION_KEY', 'primary')
    token = set_secret_scope(None)
    try:
        context = worker_context()
        set_multiplex_active(True)
        monkeypatch.setenv('HERMES_HOME', str(homes / 'profiles/second'))
        monkeypatch.setenv('SYNTHETIC_COMPANION_KEY', 'changed')
        assert context.run(home) == homes
        assert context.run(getenv, 'SYNTHETIC_COMPANION_KEY') == 'primary'
    finally:
        reset_secret_scope(token)


def test_legacy_native_retention_defers_processes_then_expires(homes, monkeypatch):
    import os
    import psutil
    from luna_core.retention import prune_native
    legacy = homes / 'opencode/data'
    legacy.mkdir(parents=True)
    raw = legacy / 'old-native.sqlite'
    raw.write_text('synthetic raw history')
    for path in (raw, legacy): os.utime(path, (1, 1))
    process = SimpleNamespace(info={'pid': 999, 'cmdline': ['native-fixture'], 'uids': SimpleNamespace(real=os.getuid())}, environ=lambda: {'XDG_DATA_HOME': str(legacy)})
    monkeypatch.setattr(psutil, 'process_iter', lambda *args: [process])
    assert prune_native(homes, days=1)['active_skipped'] == 1
    assert raw.exists()
    monkeypatch.setattr(psutil, 'process_iter', lambda *args: [])
    assert prune_native(homes, days=1)['legacy_stores'] == 1
    assert not legacy.exists()


def test_first_character_save_bootstraps_a_fresh_home(homes, client, monkeypatch):
    fresh = homes / 'fresh'
    monkeypatch.setenv('HERMES_HOME', str(fresh))
    response = client.put('/api/luna/character', json={'soul_text': '# First character\n'})
    assert response.status_code == 200, response.text
    assert (fresh / 'config.yaml').exists()
    assert (fresh / 'SOUL.md').read_text() == '# First character\n'


def test_unreachable_memory_records_a_failed_data_path_check(homes, monkeypatch):
    from luna_core import readiness, honcho
    def offline(*args, **kwargs):
        raise OSError('synthetic memory outage')
    monkeypatch.setattr(honcho.HonchoStore, 'client', offline)
    result = readiness.verify_memory()
    assert result['ok'] is False
    assert result['checks']['write_read'] is False
    assert readiness.get('memory')['ok'] is False


def test_private_files_are_never_loaded_for_group_or_nonowner_dm(homes):
    from agent.agent_init import _init_memory
    (homes / 'memories').mkdir()
    (homes / 'memories/MEMORY.md').write_text('owner-private-synthetic-fact')
    (homes / 'memories/USER.md').write_text('owner-private-synthetic-profile')
    config = {'luna': {}, 'memory': {'memory_enabled': True, 'user_profile_enabled': True}, 'telegram': {'allow_admin_from': ['owner']}}
    def agent(chat_type, user_id):
        return SimpleNamespace(enabled_toolsets=['web'], disabled_toolsets=[], tools=[], _chat_type=chat_type, _user_id=user_id)
    group = agent('group', 'owner');_init_memory(group, config, False, 'telegram')
    assert group._memory_store is None
    visitor = agent('dm', 'visitor');_init_memory(visitor, config, False, 'telegram')
    assert visitor._memory_store is None
    owner = agent('dm', 'owner');_init_memory(owner, config, False, 'telegram')
    assert owner._memory_store is not None
    assert owner._memory_store.memory_entries == ['owner-private-synthetic-fact']


def test_empty_admin_list_never_grants_privileged_luna_commands(homes):
    from gateway.slash_access import policy_for_source
    config = SimpleNamespace(platforms={'telegram': SimpleNamespace(extra={'allow_admin_from': [], 'group_allow_admin_from': []})})
    for surface in ('dm', 'group'):
        policy = policy_for_source(config, SimpleNamespace(platform='telegram', chat_type=surface))
        assert policy.enabled
        assert policy.can_run('untrusted', 'help')
        assert not policy.can_run('untrusted', 'terminal')
        assert not policy.is_admin('untrusted')
