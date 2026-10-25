"""Cross-process native worker and session leases (320 MiB reserved per worker)."""
from pathlib import Path
import os
import tempfile
import time
import hashlib

from hermes_cli._file_lock import acquire


def lease(root, session, timeout=30):
    from luna_core import config_read
    budget = config_read.section("luna", "opencode", "memory_budget_mib", default=640)
    slots = min(4, max(1, int(budget) // 320))
    user = str(os.getuid()) if hasattr(os, "getuid") else hashlib.sha256(str(Path.home()).encode()).hexdigest()[:16]
    directory = Path(tempfile.gettempdir()) / f"luna-native-workers-{user}"
    directory.mkdir(mode=0o700, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        for index in range(slots):
            worker = (directory / f"{index}.lock").open("a+")
            try:
                acquire(worker, blocking=False)
            except BlockingIOError:
                worker.close()
                continue
            except BaseException:
                worker.close()
                raise
            activity = None
            try:
                locks = root / "leases"
                locks.mkdir(parents=True, exist_ok=True, mode=0o700)
                activity = (locks / f"{session}.lock").open("a+")
                acquire(activity, blocking=False)
            except BlockingIOError:
                worker.close()
                activity.close()
                raise RuntimeError("This native conversation is already running") from None
            except BaseException:
                worker.close()
                if activity is not None: activity.close()
                raise
            return worker, activity
        if time.monotonic() >= deadline:
            raise RuntimeError("Native workers are busy. Try again when another conversation finishes.")
        time.sleep(0.1)


def idle(root, session):
    locks = root / "leases"
    locks.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = (locks / f"{session}.lock").open("a+")
    try:
        acquire(handle, blocking=False)
    except BlockingIOError:
        handle.close()
        return None
    except BaseException:
        handle.close()
        raise
    return handle
