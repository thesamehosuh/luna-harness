"""Staged companion settings transactions, shared with the engine's writer lock.

The journal contains the previous bytes, so an interrupted multi-file publication is rolled
back before the next settings operation. Journals are private (0600) and limited to settings paths.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import hashlib
import json
import os
import tempfile

from luna_core.runtime import home

_pending = ContextVar("luna_settings_pending", default=None)


class Conflict(ValueError):
    pass


def _replace(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".luna-settings-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, path.stat().st_mode & 0o777 if path.exists() else 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def exists(path):
    return Path(path).exists() or Path(path) in (_pending.get() or {})


def read(path):
    path = Path(path)
    staged = _pending.get()
    if staged is not None and path in staged:
        return staged[path]
    return path.read_text(encoding="utf-8")


def write(path, content):
    path = Path(path)
    staged = _pending.get()
    if staged is None:
        with transaction():
            write(path, content)
        return
    relative = path.resolve().relative_to(home().resolve())
    if str(relative) not in ("config.yaml", "SOUL.md") and not (
        len(relative.parts) == 2 and relative.parts[0] == "skins" and path.suffix == ".yaml"
    ):
        raise ValueError("unsupported settings path")
    staged[path] = content


def revision():
    digest = hashlib.sha256()
    for path in [home() / "config.yaml", home() / "SOUL.md", *sorted((home() / "skins").glob("*.yaml"))]:
        digest.update(str(path.relative_to(home())).encode())
        digest.update(read(path).encode() if path.exists() or path in (_pending.get() or {}) else b"")
    return digest.hexdigest()


def _recover(journal):
    if not journal.exists():
        return
    for relative, previous in json.loads(journal.read_text()).items():
        path = home() / relative
        path.resolve().relative_to(home().resolve())
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            _replace(path, previous)
    journal.unlink()


@contextmanager
def transaction(expected=None):
    if _pending.get() is not None:
        yield
        return
    from hermes_cli.config import _CONFIG_LOCK
    from hermes_cli.config_lock import settings_lock
    with _CONFIG_LOCK, settings_lock(home()):
        journal = home() / ".settings-journal.json"
        _recover(journal)
        from hermes_cli.config import ensure_hermes_home
        ensure_hermes_home()
        if expected and expected.strip('"') != revision():
            raise Conflict("Settings changed in another tab. Reload before saving.")
        staged = {}
        token = _pending.set(staged)
        try:
            yield
            if staged:
                previous = {str(p.relative_to(home())): p.read_text(encoding="utf-8") if p.exists() else None for p in staged}
                _replace(journal, json.dumps(previous))
                try:
                    for path, content in staged.items():
                        _replace(path, content)
                except BaseException:
                    _recover(journal)
                    raise
                journal.unlink()
        finally:
            _pending.reset(token)


def transactional(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        with transaction():
            return fn(*args, **kwargs)
    return call
