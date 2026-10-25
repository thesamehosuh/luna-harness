"""Idempotent startup of a profile-owned, credential-protected memory worker."""
from pathlib import Path
import json
import os
import secrets
import subprocess
import time
import urllib.request
import uuid

from luna_core.runtime import home


def _healthy(record, key):
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{int(record['port'])}/health", headers={"Authorization": "Bearer " + key})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2) as response:
            value = json.load(response)
        return value.get("nonce") == record["nonce"] and value.get("home") == str(home().resolve())
    except (OSError, ValueError, KeyError):
        return False


def ensure():
    from hermes_cli._file_lock import acquire
    from hermes_cli.product_runtime import child_environment, executable, code_root
    from hermes_cli._subprocess_compat import windows_hide_flags
    from luna_core.settings import _replace
    directory = home() / "honcho"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / ".bridge.lock").open("a+") as lock:
        acquire(lock)
        key_path = directory / ".bridge-key"
        if not key_path.is_file():
            _replace(key_path, secrets.token_urlsafe(48) + "\n")
        key = key_path.read_text().strip()
        if len(key) < 48: raise ValueError("The memory bridge credential is damaged; repair it in Setup")
        ready = directory / ".bridge-ready.json"
        if ready.is_file():
            try:
                record = json.loads(ready.read_text())
                if _healthy(record, key):
                    if record.get("release") == str(code_root(home()).resolve()): return {**record, "key": key}
                    _stop_record(record)
            except (ValueError, OSError):
                pass
        ready.unlink(missing_ok=True)
        nonce = uuid.uuid4().hex
        env = child_environment(os.environ, home())
        from hermes_cli._subprocess_compat import windows_detach_popen_kwargs
        options = windows_detach_popen_kwargs() if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen([executable(home()), "-m", "luna_cli.memory_bridge", "--nonce", nonce],
            cwd=code_root(home()), env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("The bundled memory worker could not start. Repair the runtime in Setup.")
            if ready.is_file():
                record = json.loads(ready.read_text())
                if record.get("nonce") == nonce and _healthy(record, key):
                    return {**record, "key": key}
            time.sleep(0.2)
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        raise RuntimeError("The local memory model took too long to load. Retry Setup.")


def _stop_record(record):
    import psutil
    process = psutil.Process(int(record["pid"]))
    if process.create_time() != record.get("process_start"):
        raise RuntimeError("The memory worker's process identity changed; it was not stopped")
    children = process.children(recursive=True)
    for child in children:
        try: child.terminate()
        except psutil.NoSuchProcess: pass
    process.terminate()
    _, alive = psutil.wait_procs([process, *children], timeout=5)
    for child in alive:
        try: child.kill()
        except psutil.NoSuchProcess: pass


def stop():
    from hermes_cli._file_lock import acquire
    directory = home() / "honcho"
    if not (directory / ".bridge-ready.json").exists(): return False
    with (directory / ".bridge.lock").open("a+") as lock:
        acquire(lock)
        record = json.loads((directory / ".bridge-ready.json").read_text())
        key = (directory / ".bridge-key").read_text().strip()
        if not _healthy(record, key): return False
        _stop_record(record)
        (directory / ".bridge-ready.json").unlink(missing_ok=True)
        return True
