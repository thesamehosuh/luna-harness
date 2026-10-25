"""Reentrant, process-safe lock for one profile's settings writers."""
from contextlib import contextmanager
from pathlib import Path
import threading

_guard = threading.RLock()
_locks = {}
_local = threading.local()


@contextmanager
def settings_lock(home):
    home = Path(home).resolve()
    with _guard:
        lock = _locks.setdefault(str(home), threading.RLock())
    with lock:
        held = getattr(_local, "held", set())
        if str(home) in held:
            yield
            return
        from hermes_cli._file_lock import acquire, release
        home.mkdir(parents=True, exist_ok=True)
        with (home / ".settings.lock").open("a+") as handle:
            acquire(handle)
            _local.held = held | {str(home)}
            try:
                yield
            finally:
                _local.held = held
                release(handle)
