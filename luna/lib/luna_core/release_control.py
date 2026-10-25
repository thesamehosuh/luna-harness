"""Stopped-runtime rollback for the portable desktop release pointer."""
from contextlib import closing, ExitStack
import json
from pathlib import Path
import sqlite3

from luna_core.runtime import home
from luna_core.settings import _replace


def _release(root, record):
    path = (root / record["path"]).resolve()
    if path.parent != root.resolve() / "releases" or not (path / ".ready").is_file():
        raise ValueError("The previous verified runtime is unavailable; repair the installation")
    return path


def rollback():
    from hermes_cli.config_lock import settings_lock
    from hermes_cli._file_lock import acquire
    from luna_core.data_ops import require_stopped
    root = home()
    if root.parent.name == "profiles": root = root.parent.parent
    with ExitStack() as stack:
        lock = stack.enter_context((root / ".release.lock").open("a+"))
        acquire(lock)
        stack.enter_context(settings_lock(root))
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        token = set_hermes_home_override(root)
        try:
            require_stopped()
        finally:
            reset_hermes_home_override(token)
        path = root / "current-release.json"
        current = json.loads(path.read_text())
        previous = current.get("previous")
        if not previous:
            fallback = root / "previous-release.json"
            previous = json.loads(fallback.read_text()) if fallback.exists() else None
        if not previous: raise ValueError("No previous verified runtime is available")
        target = _release(root, previous)
        _release(root, current)
        supported = json.loads((target / "luna-release.json").read_text()).get("data", {}).get("supported_luna_schemas", [])
        for owner in [root, *[p for p in (root / "profiles").glob("*") if p.is_dir()]]:
            database = owner / "luna-state.db"
            if database.exists():
                with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
                    row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
                if row and int(row[0]) not in supported:
                    raise ValueError("The prior runtime cannot read this data schema. Restore its compatible backup before rolling back.")
        prior = {key: current[key] for key in ("format", "path", "version") if key in current}
        value = {**previous, "previous": prior}
        # Current + previous change together. No symlink privileges or two-file swap window.
        _replace(path, json.dumps(value))
        return {"ok": True, "version": previous.get("version"), "detail": "Previous runtime selected. Reopen Luna to use it. Personal data was retained."}
