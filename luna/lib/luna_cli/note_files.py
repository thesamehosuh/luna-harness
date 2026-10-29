"""Dashboard editors for profile-owned Markdown notes, with shared writer locks."""
from __future__ import annotations

import hashlib
from luna_core import config_read, people
from luna_core.runtime import home
from luna_core.settings import _replace
from tools.memory_tool_store import MemoryStore, ENTRY_DELIMITER, _scan_memory_content


class Conflict(ValueError):
    pass


def _catalog():
    from luna_cli.api_models import _registry
    from luna_cli.groups import _catalog as groups
    from luna_core.group_memory import directory
    config = config_read.load_config().get('memory') or {}
    files = {
        'memory': dict(id='memory', name='MEMORY.md', scope='Owner DM', kind='notes',
                       description='Private notes your companion keeps about your work, preferences and ongoing plans.',
                       limit=int(config.get('memory_char_limit', 2200)), enabled=config.get('memory_enabled', True),
                       path=home() / 'memories/MEMORY.md'),
        'user': dict(id='user', name='USER.md', scope='Owner DM', kind='notes',
                     description='Your private profile: what your companion should know about you.',
                     limit=int(config.get('user_char_limit', 1375)), enabled=config.get('user_profile_enabled', True),
                     path=home() / 'memories/USER.md'),
        'people': dict(id='people', name='PEOPLE.md', scope='Shared directory and group entries', kind='people',
                       description='Names, aliases, pronouns and short roles. Group and DM sections stay in their own conversation.',
                       limit=people.MAX_BYTES, enabled=config.get('user_profile_enabled', True), path=people.path()),
    }
    conn, _ = _registry()
    try:
        for group in groups(conn):
            scope = {key: group[key] for key in ('platform', 'chat_id', 'thread_id')}
            key = 'group-' + group['id']
            files[key] = dict(id=key, name='MEMORY.md', scope=group['name'], kind='notes', group=scope,
                              description='Public notes for this group and topic. Private owner notes belong in the Owner DM files.',
                              limit=int(config.get('memory_char_limit', 2200)), enabled=config.get('memory_enabled', True),
                              path=directory(scope) / 'MEMORY.md')
    finally:
        conn.close()
    return files


def catalog():
    return {'files': [{key: value for key, value in item.items() if key not in {'path', 'group'}}
                      for item in _catalog().values()]}


def _file(file_id):
    item = _catalog().get(file_id)
    if item is None:
        raise ValueError('Choose a note file from this profile')
    path = item['path']
    for parent in [path, *path.parents]:
        if parent == home():
            break
        if parent.is_symlink():
            raise ValueError('Note files cannot use linked files or directories')
    return item


def _read(path):
    if path.exists() and path.stat().st_size > people.MAX_BYTES:
        raise ValueError('This note file is too large to edit')
    return path.read_text(encoding='utf-8') if path.exists() else ''


def _revision(file_id, text):
    return hashlib.sha256((str(home().resolve()) + '\0' + file_id + '\0' + text).encode()).hexdigest()


def read(file_id):
    item = _file(file_id)
    content = _read(item['path'])
    return {**{key: value for key, value in item.items() if key not in {'path', 'group'}},
            'content': content, 'revision': _revision(file_id, content)}


def save(file_id, content, revision):
    if not isinstance(content, str) or len(content.encode()) > people.MAX_BYTES:
        raise ValueError('Keep the note file within 256 KiB')
    item = _file(file_id)
    from hermes_cli.config_lock import settings_lock
    lock = settings_lock(home()) if item['kind'] == 'people' else MemoryStore._file_lock(item['path'])
    with lock:
        # Recheck links under the writer lock and compare the exact on-disk bytes.
        item = _file(file_id)
        if _revision(file_id, _read(item['path'])) != revision:
            raise Conflict('This file changed in another tab or a companion turn. Your draft is still here; reload the saved file before applying your changes.')
        if item['kind'] == 'people':
            entries = people.parse(content, strict=True)
            from luna_cli.api_models import _registry
            conn, registry = _registry()
            try:
                for platform, uid, *_ in entries:
                    if registry.get_any(platform, uid) is None:
                        raise ValueError(f'Unknown transport identity {platform} / {uid}. Add the person in People first.')
            finally:
                conn.close()
        else:
            entries = MemoryStore._parse_entries(content)
            content = ENTRY_DELIMITER.join(entries)
            if len(content) > item['limit']:
                raise ValueError(f"Keep {item['name']} within {item['limit']:,} characters")
            for entry in entries:
                if error := _scan_memory_content(entry):
                    raise ValueError(error)
            if item.get('group'):
                from luna_core.group_memory import GroupMemoryStore
                GroupMemoryStore(item['group'])
        _replace(item['path'], content)
    return read(file_id)
