"""New cloned companions never inherit another profile's live memory service."""
import hashlib
import json
from pathlib import Path
import re
import shutil


def detach_clone(staging, destination):
    from hermes_cli.product_runtime import ROOT
    from luna_core.configedit import write_config_value
    from luna_core.settings import _replace
    import yaml
    staging, destination = Path(staging), Path(destination)
    path = staging / 'config.yaml'
    text = path.read_text()
    config = yaml.safe_load(text) or {}
    if not isinstance(config.get('luna'), dict):
        return
    workspace = 'luna_' + hashlib.sha256(str(destination.resolve()).encode()).hexdigest()[:16]
    for key, value in [(('honcho', 'workspace'), workspace), (('honcho', 'baseUrl'), 'http://localhost:8000'),
                       (('luna', 'setup', 'memory'), 'pending'), (('luna', 'logger', 'sync_honcho'), False),
                       (('luna', 'setup', 'jev'), 'pending'), (('luna', 'ambient', 'enabled'), False),
                       (('luna', 'ambient', 'watched_chats'), [])]:
        text = write_config_value(text, key, value)
    _replace(path, text)
    # The copied directory contains host process leases, bridge credentials and
    # Compose connection state. The live database is an external Docker volume;
    # copying these files never copies its contents or creates a new service.
    stack = staging / 'honcho'
    if stack.is_symlink():
        stack.unlink()
    elif stack.is_dir():
        shutil.rmtree(stack)
    template = json.loads((ROOT / 'luna/config/honcho.json.luna').read_text())
    template.setdefault('hosts', {}).setdefault('hermes', {})['workspace'] = workspace
    _replace(staging / 'honcho.json', json.dumps(template, indent=2) + '\n')
    env = staging / '.env'
    if env.exists():
        keys = {'LUNA_HONCHO_WORKSPACE', 'LUNA_HONCHO_BASE_URL', 'HONCHO_BASE_URL',
                'LUNA_HONCHO_JSON', 'HERMES_HONCHO_HOST'}
        lines = [line for line in env.read_text().splitlines()
                 if not (match := re.match(r'\s*(?:export\s+)?([A-Z_]+)\s*=', line)) or match[1] not in keys]
        _replace(env, '\n'.join(lines) + '\n')
