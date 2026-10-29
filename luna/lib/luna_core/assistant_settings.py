"""Owner-only, deliberately narrow assistant access to dashboard settings."""
import json
import os


def _owners():
    from luna_cli import tune
    cfg = tune._load_yaml(tune.config_path())
    owners = (cfg.get('telegram') or {}).get('allow_admin_from') or []
    return {str(x) for x in owners} if isinstance(owners, list) else set()


def _authorized():
    # Task-local transport bindings are authoritative; environment fallback is not proof.
    from gateway import session_context as session
    from agent.delegation_context import is_delegated_child_context
    if is_delegated_child_context() or os.getenv('HERMES_CRON_SESSION') or os.getenv('HERMES_KANBAN_TASK'):
        return False
    get = lambda key: session._VAR_MAP[key].get()
    platform = get('HERMES_SESSION_PLATFORM')
    chat_type = get('HERMES_SESSION_CHAT_TYPE')
    uid = get('HERMES_SESSION_USER_ID')
    chat = get('HERMES_SESSION_CHAT_ID')
    message = get('HERMES_SESSION_MESSAGE_ID')
    cron = get('HERMES_CRON_SESSION')
    return (platform == 'telegram' and chat_type == 'dm' and isinstance(uid, str)
            and uid.isdecimal() and uid == chat and uid in _owners()
            and isinstance(message, str) and message.isdecimal() and cron == '')


_BOUNDS = {'settle_seconds': (0, 600), 'poll_seconds': (1, 300), 'stale_after_minutes': (1, 1440)}
_BOOL = {'enabled', 'dry_run', 'honcho_enabled'}


def _actual(setting):
    if setting == 'honcho_enabled':
        from luna_cli import tune
        cfg = tune._load_yaml(tune.config_path())
        luna = cfg.get('luna') or {}
        memory = cfg.get('memory') or {}
        choice = (luna.get('setup') or {}).get('memory')
        states = [memory.get('memory_enabled'), memory.get('user_profile_enabled'),
                  (luna.get('logger') or {}).get('sync_honcho')]
        if choice == 'enabled' and all(value is True for value in states):
            return True
        if choice == 'skipped' and all(value is False for value in states):
            return False
        return None
    from luna_cli.behaviour import behaviour_bundle
    return behaviour_bundle().get(setting)


def tool_handler(args, **kwargs):
    try:
        if not _authorized():
            return json.dumps({'ok': False, 'error': 'Available only to the configured owner in a direct Telegram conversation.'})
        if not isinstance(args, dict) or set(args) - {'action', 'setting', 'value'}:
            raise ValueError('Invalid arguments')
        if args.get('action') == 'inspect' and set(args) == {'action'}:
            return json.dumps({'ok': True, 'settings': {key: _actual(key) for key in sorted(_BOOL | _BOUNDS.keys())}})
        setting, value = args.get('setting'), args.get('value')
        if args.get('action') != 'update' or set(args) != {'action', 'setting', 'value'} or setting not in _BOOL | _BOUNDS.keys():
            raise ValueError('Choose a supported setting and an explicit value')
        if setting in _BOOL and type(value) is not bool:
            raise ValueError('This setting requires a boolean')
        if setting in _BOUNDS and (type(value) is not int or not _BOUNDS[setting][0] <= value <= _BOUNDS[setting][1]):
            raise ValueError('Value is outside the allowed integer range')
        # The tool call is model-controlled and cannot establish owner intent.
        # Until transport-origin, value-bound authorization exists, fail closed.
        return json.dumps({'ok': False, 'error': 'Changes are unavailable here; use the Luna dashboard.'})
    except ValueError as exc:
        return json.dumps({'ok': False, 'error': str(exc)})
    except Exception:
        return json.dumps({'ok': False, 'error': 'Unable to inspect settings. Check the dashboard.'})


TOOL_SCHEMA = {'name': 'luna_settings', 'description': 'Inspect basic Luna dashboard settings. Changes are unavailable via this tool; direct the owner to the Luna dashboard.', 'parameters': {'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['inspect', 'update']}, 'setting': {'type': 'string', 'enum': sorted(_BOOL | _BOUNDS.keys())}, 'value': {'type': ['boolean', 'integer']}}, 'required': ['action'], 'additionalProperties': False}}
