import json

from gateway import session_context as session


def test_injected_tool_call_cannot_write_without_transport_consent(monkeypatch):
    from luna_core import assistant_settings
    from luna_cli import behaviour
    monkeypatch.setattr(assistant_settings, '_owners', lambda: {'42'})
    writes = []
    monkeypatch.setattr(behaviour, 'write_behaviour', lambda values: writes.append(values) or {'results': {'dry_run': {'ok': True}}})
    monkeypatch.setattr(behaviour, 'behaviour_bundle', lambda: {'dry_run': True})
    session.set_session_vars(platform='telegram', chat_type='dm', user_id='42', chat_id='42', message_id='8', cron_session='')
    try:
        # An instruction from a tool result/page/history is indistinguishable here from a model call.
        for setting, value in [('dry_run', True), ('enabled', True), ('honcho_enabled', True),
                               ('poll_seconds', 4), ('settle_seconds', 0), ('stale_after_minutes', 5)]:
            for extra in ({}, {'confirmed': True}):
                out = json.loads(assistant_settings.tool_handler({'action': 'update', 'setting': setting, 'value': value, **extra}))
                assert not out['ok']
        assert writes == []
    finally:
        session.reset_session_vars()


def test_unknown_context_is_denied_even_if_environment_claims_owner(monkeypatch, tmp_path):
    from luna_core import assistant_settings
    monkeypatch.setenv('HERMES_SESSION_PLATFORM', 'telegram')
    monkeypatch.setenv('HERMES_SESSION_CHAT_TYPE', 'dm')
    monkeypatch.setenv('HERMES_SESSION_USER_ID', '42')
    monkeypatch.setattr(assistant_settings, '_owners', lambda: {'42'})
    session.reset_session_vars()
    result = json.loads(assistant_settings.tool_handler({'action': 'inspect'}))
    assert result['ok'] is False


def test_owner_can_inspect_but_not_update_curated_setting(monkeypatch):
    from luna_core import assistant_settings
    monkeypatch.setattr(assistant_settings, "_owners", lambda: {"42"})
    from luna_cli import behaviour
    values = {"dry_run": False, "enabled": False, "settle_seconds": 1, "poll_seconds": 5, "stale_after_minutes": 10}
    monkeypatch.setattr(behaviour, "behaviour_bundle", lambda: dict(values))
    def write(updates):
        values.update(updates)
        return {"results": {key: {"ok": True} for key in updates}}
    monkeypatch.setattr(behaviour, "write_behaviour", write)
    session.set_session_vars(platform="telegram", chat_type="dm", user_id="42", chat_id="42", message_id="8", cron_session="")
    try:
        monkeypatch.setattr(assistant_settings, '_actual', lambda key: values.get(key))
        inspected = json.loads(assistant_settings.tool_handler({'action': 'inspect'}))
        assert inspected['ok'] and inspected['settings']['dry_run'] is False
        out = json.loads(assistant_settings.tool_handler({"action": "update", "setting": "dry_run", "value": True}))
        assert out["ok"] is False
        assert values['dry_run'] is False
    finally:
        session.reset_session_vars()


def test_existing_luna_room_plugin_registers_settings_tool():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / 'plugins/luna-room/__init__.py'
    spec = importlib.util.spec_from_file_location('luna_room_settings_test', path)
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    calls = []
    class Context:
        def register_tool(self, **kwargs): calls.append(kwargs['name'])
        def register_hook(self, *args): pass
    plugin.register(Context())
    assert 'luna_settings' in calls


def test_existing_install_owner_dm_receives_toolset_without_template_entry():
    from luna_core.surface_policy import toolsets
    from types import SimpleNamespace
    from gateway.config import Platform
    config = {'luna': {}, 'telegram': {'allow_admin_from': ['42']}}
    source = SimpleNamespace(platform=Platform.TELEGRAM, chat_type='dm', user_id='42', chat_id='42')
    assert 'luna_settings' in toolsets(config, source, ['web'])


def test_gateway_context_reaches_tool_executor_and_policy(monkeypatch):
    import asyncio
    from gateway.run import GatewayRunner
    from gateway.config import Platform
    from gateway.session import SessionContext, SessionSource
    from luna_core import assistant_settings
    monkeypatch.setattr(assistant_settings, '_owners', lambda: {'42'})
    monkeypatch.setattr(assistant_settings, '_actual', lambda key: False)
    runner = GatewayRunner.__new__(GatewayRunner)
    runner.adapters = {}
    monkeypatch.setattr(runner, '_delivery_adapter_for', lambda source: None)
    config = {'luna': {}, 'telegram': {'allow_admin_from': ['42']}, 'platform_toolsets': {'telegram': ['web']}}

    async def run(source):
        enabled, _ = runner._resolve_turn_toolsets(config, source, 'telegram')
        tokens = runner._set_session_env(SessionContext(source=source, connected_platforms=[], home_channels={}))
        try:
            result = await runner._run_in_executor_with_context(assistant_settings.tool_handler, {'action': 'inspect'})
            injected = await runner._run_in_executor_with_context(assistant_settings.tool_handler, {'action': 'update', 'setting': 'dry_run', 'value': True})
            return enabled, json.loads(result), json.loads(injected)
        finally:
            runner._clear_session_env(tokens)

    owner = SessionSource(platform=Platform.TELEGRAM, chat_id='42', user_id='42', chat_type='dm', message_id='8')
    group = SessionSource(platform=Platform.TELEGRAM, chat_id='99', user_id='42', chat_type='group', message_id='9')
    try:
        enabled, result, injected = asyncio.run(run(owner))
        assert 'luna_settings' in enabled and result['ok'] and not injected['ok']
        enabled, result, injected = asyncio.run(run(group))
        assert 'luna_settings' not in enabled and not result['ok'] and not injected['ok']
    finally:
        if getattr(runner, '_executor', None):
            runner._executor.shutdown(wait=True)


def test_config_tool_is_never_exposed_in_groups_even_with_host_access():
    from luna_core.surface_policy import toolsets
    from types import SimpleNamespace
    config = {"luna": {"access": {"group_host_access": True}}, "telegram": {"allow_admin_from": ["42"]}}
    source = SimpleNamespace(chat_type="group", user_id="42")
    assert "luna_settings" not in toolsets(config, source, ["luna_settings", "web"])


def test_honcho_update_does_not_start_service(monkeypatch):
    from luna_core import assistant_settings
    from luna_cli import onboarding, tune
    monkeypatch.setattr(assistant_settings, "_owners", lambda: {"42"})
    monkeypatch.setattr(tune, "_load_yaml", lambda path: {"luna": {"setup": {"memory": "enabled"}, "logger": {"sync_honcho": True}}, "memory": {"memory_enabled": True, "user_profile_enabled": True}})
    called = []
    def service(enabled):
        called.append(enabled)
        return {"ok": False, "detail": "not healthy"}
    monkeypatch.setattr(onboarding, "set_memory_service", service)
    session.set_session_vars(platform="telegram", chat_type="dm", user_id="42", chat_id="42", message_id="8", cron_session="")
    try:
        out = json.loads(assistant_settings.tool_handler({"action": "update", "setting": "honcho_enabled", "value": True}))
        assert called == []
        assert out["ok"] is False
    finally: session.reset_session_vars()


def test_update_does_not_use_readback_to_authorize(monkeypatch):
    from luna_core import assistant_settings
    from luna_cli import behaviour
    monkeypatch.setattr(assistant_settings, "_owners", lambda: {"42"})
    monkeypatch.setattr(behaviour, "write_behaviour", lambda updates: {"results": {"dry_run": {"ok": True}}})
    monkeypatch.setattr(behaviour, "behaviour_bundle", lambda: {"dry_run": False})
    session.set_session_vars(platform="telegram", chat_type="dm", user_id="42", chat_id="42", message_id="8", cron_session="")
    try:
        out = json.loads(assistant_settings.tool_handler({"action": "update", "setting": "dry_run", "value": True}))
        assert out["ok"] is False
    finally: session.reset_session_vars()


def test_disallows_invalid_and_unknown_values(monkeypatch):
    from luna_core import assistant_settings
    monkeypatch.setattr(assistant_settings, "_owners", lambda: {"42"})
    session.set_session_vars(platform="telegram", chat_type="dm", user_id="42", chat_id="42", message_id="8", cron_session="")
    try:
        for setting, value in [("poll_seconds", True), ("poll_seconds", 0), ("secret", "x"), ("honcho_enabled", "true")]:
            assert not json.loads(assistant_settings.tool_handler({"action": "update", "setting": setting, "value": value}))["ok"]
    finally: session.reset_session_vars()


def test_denies_untrusted_contexts(monkeypatch):
    from luna_core import assistant_settings
    monkeypatch.setattr(assistant_settings, "_owners", lambda: {"42"})
    for values in [
        dict(platform="telegram", chat_type="group", user_id="42", chat_id="42", message_id="8", cron_session=""),
        dict(platform="telegram", chat_type="dm", user_id="43", chat_id="43", message_id="8", cron_session=""),
        dict(platform="telegram", chat_type="dm", user_id="42", chat_id="42", message_id="8", cron_session="1"),
        dict(platform="telegram", chat_type="dm", user_id="42", chat_id="42", message_id="", cron_session=""),
        dict(platform="api_server", chat_type="dm", user_id="42", chat_id="42", message_id="8", cron_session=""),
    ]:
        session.set_session_vars(**values)
        try: assert not json.loads(assistant_settings.tool_handler({"action": "inspect"}))["ok"]
        finally: session.reset_session_vars()


def test_honcho_readback_detects_inconsistent_configuration(monkeypatch):
    from luna_core import assistant_settings
    from luna_cli import tune
    monkeypatch.setattr(tune, "_load_yaml", lambda path: {"luna": {"setup": {"memory": "enabled"}, "logger": {"sync_honcho": False}}, "memory": {"memory_enabled": True, "user_profile_enabled": True}})
    assert assistant_settings._actual("honcho_enabled") is None


def test_update_leaves_real_isolated_config_unchanged(monkeypatch, tmp_path):
    from luna_core import assistant_settings
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "config.yaml").write_text("telegram:\n  allow_admin_from: ['42']\nluna:\n  ambient:\n    dry_run: false\n")
    session.set_session_vars(platform="telegram", chat_type="dm", user_id="42", chat_id="42", message_id="8", cron_session="")
    try:
        out = json.loads(assistant_settings.tool_handler({"action": "update", "setting": "dry_run", "value": True}))
        assert out["ok"] is False
        import yaml
        assert yaml.safe_load((home / "config.yaml").read_text())["luna"]["ambient"]["dry_run"] is False
    finally: session.reset_session_vars()


def test_delegated_and_environment_cron_cannot_borrow_owner_identity(monkeypatch):
    from luna_core import assistant_settings
    from agent import delegation_context
    monkeypatch.setattr(assistant_settings, "_owners", lambda: {"42"})
    session.set_session_vars(platform="telegram", chat_type="dm", user_id="42", chat_id="42", message_id="8", cron_session="")
    try:
        monkeypatch.setattr(delegation_context, "is_delegated_child_context", lambda: True)
        assert not json.loads(assistant_settings.tool_handler({"action": "inspect"}))["ok"]
        monkeypatch.setattr(delegation_context, "is_delegated_child_context", lambda: False)
        monkeypatch.setenv("HERMES_CRON_SESSION", "1")
        assert not json.loads(assistant_settings.tool_handler({"action": "inspect"}))["ok"]
    finally: session.reset_session_vars()


def test_honcho_disable_does_not_start_managed_workflow(monkeypatch):
    from luna_core import assistant_settings
    from luna_cli import onboarding
    monkeypatch.setattr(assistant_settings, "_owners", lambda: {"42"})
    monkeypatch.setattr(assistant_settings, "_actual", lambda name: False)
    calls = []
    monkeypatch.setattr(onboarding, "set_memory_service", lambda enabled: calls.append(enabled) or {"ok": True})
    session.set_session_vars(platform="telegram", chat_type="dm", user_id="42", chat_id="42", message_id="8", cron_session="")
    try:
        out = json.loads(assistant_settings.tool_handler({"action": "update", "setting": "honcho_enabled", "value": False}))
        assert calls == [] and not out["ok"]
    finally: session.reset_session_vars()
