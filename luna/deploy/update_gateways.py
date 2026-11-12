"""Pause this installation's running companions while publishing a runtime."""
from contextlib import contextmanager, ExitStack
import os
import json
from pathlib import Path
import signal
import subprocess
import time


def _env(profile):
    env = dict(os.environ, HERMES_HOME=str(profile), LUNA_HOME=str(profile))
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "_HERMES_GATEWAY",
                "HERMES_PARENT_PID", "HERMES_DASHBOARD_SESSION_TOKEN", "LUNA_DESKTOP_NONCE"):
        env.pop(key, None)
    return env


def _action_env(python, profile):
    if profile.parent.name != "profiles":
        return _env(profile)
    # Reuse the dashboard's profile credential boundary, including secret-source
    # keys which need not appear in the default profile's .env file.
    code = ("import json,sys; from hermes_cli.web_server_gateway import _profile_action_environment; "
            "print(json.dumps(_profile_action_environment(['-p',sys.argv[1],'gateway','start'])))")
    result = subprocess.run([str(python), "-I", "-c", code, profile.name],
                            env=_env(profile.parent.parent), stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, check=True, timeout=30)
    env = json.loads(result.stdout)
    env.update(HERMES_HOME=str(profile), LUNA_HOME=str(profile))
    for key in ("HERMES_PARENT_PID", "HERMES_DASHBOARD_SESSION_TOKEN", "LUNA_DESKTOP_NONCE"):
        env.pop(key, None)
    return env


def _check_owner(python, profile):
    # A service definition may bypass Luna's runtime handoff. Until its actual
    # command is verified, refuse publication even for stopped services.
    code = """import sys
from hermes_cli import gateway
kind = gateway._installed_service_kind()
sys.exit(4 if kind else 0)
"""
    result = subprocess.run([str(python), "-I", "-c", code], env=_env(profile),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=30)
    if result.returncode == 4:
        raise RuntimeError("An installed companion service may reference the old runtime. Update is blocked until its configuration is verified.")
    if result.returncode:
        raise RuntimeError("Could not safely identify the companion's service. Check Control Center.")


def _running(python, profile):
    result = subprocess.run(
        [str(python), "-I", "-c", "from gateway.status import is_gateway_running; import sys; sys.exit(0 if is_gateway_running(cleanup_stale=False) else 3)"],
        env=_env(profile), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=30,
    )
    if result.returncode not in (0, 3):
        raise RuntimeError("Could not check the companion's state. The update was stopped.")
    return result.returncode == 0


def _wait(python, profile, running, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _running(python, profile) == running:
            return
        time.sleep(0.5)
    raise RuntimeError("The companion did not finish starting or stopping. Check Control Center.")


def _stop(python, profile):
    subprocess.run([str(python), "-m", "luna_cli.main", "gateway", "stop"], env=_action_env(python, profile),
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=True, timeout=240)
    _wait(python, profile, False, 240)


def _start(python, profile):
    # A portable gateway may run in the foreground; detach it from the installer.
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0
    subprocess.Popen([str(python), "-m", "luna_cli.main", "gateway", "start"], env=_action_env(python, profile),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=os.name != "nt", creationflags=flags)
    _wait(python, profile, True, 120)


def _runtime_lock(handle, unlock=False):
    # Match gateway.status's protocol without importing runtime dependencies into
    # the stdlib-only bootstrap installer. Windows locks beyond the JSON record.
    if os.name == "nt":
        import msvcrt
        handle.seek(1024 * 1024)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def stopped_gateway_locks(home):
    """Fence legacy gateway starts while publishing; never stop or restart one.

    The caller holds .release.lock, which new runtimes honor even for newly
    created profiles. Existing runtimes already honor each home's gateway.lock.
    Hold those locks too so the first upgrade also excludes their startup.
    """
    home = Path(home).resolve()
    profiles = [home, *sorted(p for p in (home / "profiles").glob("*") if p.is_dir())]
    with ExitStack() as stack:
        for profile in profiles:
            if profile.is_symlink():
                raise ValueError("A profile home is a symlink; update it separately")
            handle = stack.enter_context((profile / "gateway.lock").open("a+", encoding="utf-8"))
            try:
                _runtime_lock(handle)
            except OSError as exc:
                raise ValueError("Stop the affected profile gateways in System before updating") from exc
            stack.callback(_runtime_lock, handle, True)
        yield


@contextmanager
def paused_gateways(home, old_python, selected_python):
    """Resume only gateways that were running, including after an install error."""
    profiles = [home, *sorted(p for p in (home / "profiles").glob("*") if p.is_dir() and not p.is_symlink())]
    running = [profile for profile in profiles if _running(old_python, profile)]
    for profile in profiles:
        _check_owner(old_python, profile)
    paused = []
    previous_handlers = {}
    def interrupted(signum, frame):
        raise InterruptedError("Update cancelled; restoring your companions.")
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[sig] = signal.signal(sig, interrupted)
        for profile in running:
            # Record before attempting stop, so a partially successful stop is recovered.
            paused.append(profile)
            print("LUNA_STAGE stopping-companions", flush=True)
            _stop(old_python, profile)
        yield
    finally:
        # Cancellation has already interrupted publication; further signals must
        # not interrupt restoration or strand the remaining profiles.
        for sig in previous_handlers:
            signal.signal(sig, signal.SIG_IGN)
        failures = []
        for profile in paused:
            try:
                if not _running(old_python, profile):
                    print("LUNA_STAGE starting-companions", flush=True)
                    _start(selected_python(), profile)
            except Exception:
                failures.append(profile)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        if failures:
            raise RuntimeError("Luna could not restart every companion. Open Control Center to start them.")
