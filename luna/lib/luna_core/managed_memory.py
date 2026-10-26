"""Resumable, home-owned Honcho setup; no gateway or unrelated Docker lifecycle changes."""
from pathlib import Path
import hashlib
import json
import shutil
import socket
import subprocess
import time
import threading
from functools import wraps

_restores = {}
_restore_lock = threading.Lock()

from luna_core.runtime import home
from luna_core.settings import _replace


def status():
    path = home() / "honcho/.setup-status.json"
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return {"stage": "idle", "detail": "Memory has not been set up"}


def _progress(stage, detail, **extra):
    _replace(home() / "honcho/.setup-status.json", json.dumps({"stage": stage, "detail": detail, "at": time.time(), **extra}))


def _contract(stack):
    from luna_core.embeddings import MODEL
    wanted = {"model": MODEL["id"], "revision": MODEL["revision"], "dimensions": MODEL["dimensions"],
              "weights": MODEL["files"]["model.onnx"]["sha256"], "pooling": MODEL["pooling"]}
    path = stack / ".embedding-contract.json"
    if path.exists() and json.loads(path.read_text()) != wanted:
        raise ValueError("This memory index uses a different embedding model. Export/backup and migrate it before switching models; the existing database has been kept.")
    env = stack / ".env"
    if not path.exists() and env.exists():
        from luna_core.env import parse_env_file
        values = parse_env_file(env)
        if values.get("EMBEDDING_MODEL_CONFIG__MODEL") != MODEL["id"] or values.get("EMBEDDING_VECTOR_DIMENSIONS") != str(MODEL["dimensions"]):
            raise ValueError("An existing memory stack uses another embedding model. A separate migration is required; Luna has kept its settings and data.")
    return path, wanted


def _serialized_lifecycle(function):
    @wraps(function)
    def serialized(*args, **kwargs):
        stack = home() / "honcho"
        if not stack.is_dir():
            return function(*args, **kwargs)
        from hermes_cli._file_lock import acquire
        with (stack / ".lifecycle.lock").open("a+") as lock:
            acquire(lock)
            return function(*args, **kwargs)
    return serialized


@_serialized_lifecycle
def restore():
    """Restore an already-enabled owned worker after login/reboot, never install Docker."""
    from luna_core import config_read, memory_worker
    from luna_core.data_ops import compose_command
    from luna_core.env import parse_env_file
    from luna_cli.onboarding import _seed_honcho_env
    stack = home() / "honcho"
    if config_read.section("luna", "setup", "memory", default="pending") != "enabled" or not (stack / ".embedding-contract.json").is_file():
        return
    key = str(home().resolve())
    with _restore_lock:
        if time.monotonic() - _restores.get(key, 0) < 30: return
        _restores[key] = time.monotonic()
    try:
        _contract(stack)
        worker = memory_worker.ensure()
        values = parse_env_file(stack / ".env")
        from luna_core.memory_network import worker_url
        wanted = worker_url(worker["port"])
        if values.get("DERIVER_MODEL_CONFIG__OVERRIDES__BASE_URL") != wanted:
            _seed_honcho_env(stack, refresh=True, worker=worker)
        args = ("up", "-d", "api", "deriver")
        from luna_core.memory_network import connection, finish_loopback
        if connection().get("mode") == "loopback":
            def run(*compose_args):
                result = subprocess.run(compose_command(stack, *compose_args), capture_output=True, text=True, timeout=120)
                if result.returncode:
                    raise RuntimeError("Memory database services did not start")
                return result
            run("up", "-d", "--wait", "database", "redis")
            if finish_loopback(stack, run):
                args = ("up", "-d", "--force-recreate", "api", "deriver")
        proc = subprocess.run(compose_command(stack, *args), capture_output=True, timeout=120)
        if proc.returncode: raise RuntimeError("Memory containers need repair in Setup")
    except Exception:
        with _restore_lock:
            _restores.pop(key, None)
        _progress("degraded", "The saved memory worker needs attention. Open Memory → Setup and repair.")


@_serialized_lifecycle
def disable():
    """Stop only an enabled managed stack. A fresh skip performs no Docker operation."""
    stack = home() / "honcho"
    if not (stack / ".embedding-contract.json").is_file(): return
    from luna_core import memory_worker
    from luna_core.data_ops import compose_command
    try: memory_worker.stop()
    except Exception: pass
    try: subprocess.run(compose_command(stack, "stop"), capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError): pass
    _progress("disabled", "Memory is skipped; its data has been retained")


def setup(timeout=180):
    from hermes_cli._file_lock import acquire
    from hermes_cli._subprocess_compat import windows_hide_flags
    from luna_core import docker_setup, memory_reasoning, memory_worker, settings, readiness
    from luna_core.configedit import write_config_value
    from luna_cli import onboarding, tune
    stack = home() / "honcho"
    if not stack.exists():
        source = Path(__file__).resolve().parents[3] / "luna/honcho"
        shutil.copytree(source, stack)
    with (stack / ".setup.lock").open("a+") as lock:
        try: acquire(lock, blocking=False)
        except BlockingIOError:
            return {"ok": False, "detail": "Memory setup is already running", "progress": status()}
        try:
            if (onboarding._config().get("luna", {}).get("memory_stack") or {}).get("embedding_source", "bundled") != "bundled":
                raise ValueError("This guided setup provisions the bundled model. Keep an existing external embedding stack through Advanced settings; changing its index requires a separate migration.")
            contract_path, contract = _contract(stack)
            selected = memory_reasoning.route()
            _progress("reasoning", f"Checking the selected memory model ({selected['model']})…")
            try:
                memory_reasoning.complete({"messages": [{"role": "user", "content": 'Return exactly {"ok":true} as JSON.'}],
                    "response_format": {"type": "json_schema", "json_schema": {"name": "luna_setup", "strict": True,
                        "schema": {"type": "object", "properties": {"ok": {"type": "boolean", "const": True}}, "required": ["ok"], "additionalProperties": False}}}})
            except Exception:
                raise RuntimeError("The selected memory model could not complete its structured response check. Retry when it is available, or choose another configured model.") from None
            _progress("docker", "Checking Docker and Compose…")
            prefix = docker_setup.ensure(_progress)
            onboarding.set_choice("honcho", "enabled")
            _progress("embeddings", "Loading the bundled multilingual memory model…")
            worker = memory_worker.ensure()
            if not (stack / ".env").exists():
                # Reserve a candidate; Compose's bind is authoritative and detects races.
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
                with settings.transaction():
                    text = write_config_value(settings.read(tune.config_path()), ["honcho", "baseUrl"], f"http://127.0.0.1:{port}")
                    settings.write(tune.config_path(), text)
            written = onboarding._seed_honcho_env(stack, refresh=True, worker=worker)
            _replace(contract_path, json.dumps(contract, sort_keys=True))
            from luna_core import memory_network
            from luna_core.data_ops import compose_command
            _progress("connection", "Preparing local memory connections…")
            mode = memory_network.configure(stack, worker, prefix)
            def run(*args):
                result = subprocess.run(compose_command(stack, *map(str, args)), cwd=stack, capture_output=True, text=True,
                    timeout=max(180, timeout + 120), creationflags=windows_hide_flags())
                if result.returncode:
                    # CLI diagnostics can include rendered credentials; do not send them to the browser.
                    raise RuntimeError("The managed memory containers could not finish this step. Retry setup; existing volumes are retained.")
                return result
            _progress("database", "Preparing the private memory database and cache…")
            run("stop", "api", "deriver")
            run("up", "-d", "--wait", "--wait-timeout", timeout, "database", "redis")
            if mode == "loopback": memory_network.finish_loopback(stack, run)
            _progress("schema", "Checking the embedding schema before accepting memories…")
            run("run", "--rm", "--no-deps", "bootstrap")
            _progress("honcho", "Starting Honcho and its memory worker…")
            run("up", "-d", "--wait", "--wait-timeout", timeout, "api", "deriver")
            # Read the actual owned Compose service's publication, never assume a listener's identity.
            if mode == "loopback":
                from luna_core.env import parse_env_file
                port = int(parse_env_file(stack / ".env")["HONCHO_PORT"])
            else:
                publication = run("port", "api", "8000").stdout.strip()
                port = int(publication.rsplit(":", 1)[1])
            with settings.transaction():
                text = write_config_value(settings.read(tune.config_path()), ["honcho", "baseUrl"], f"http://127.0.0.1:{port}")
                settings.write(tune.config_path(), text)
            _progress("verification", "Verifying writes, search, attributed group memory and persistence…")
            def restart():
                _progress("restart-check", "Checking that memory survives a restart…")
                run("restart", "api", "deriver")
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if onboarding._probe_health(f"http://127.0.0.1:{port}"): return
                    time.sleep(1)
                raise RuntimeError("The managed memory API did not recover after restart")
            verified = readiness.verify_memory(restart=restart)
            if not verified["ok"]:
                _progress("degraded", "Memory needs attention. Retry checks; existing data is kept.", checks=verified.get("checks", {}))
                return {"ok": False, "detail": "Memory started, but its end-to-end checks did not all pass. Retry verification.", "verification": verified}
            _progress("ready", "Memory is ready", checks=verified["checks"])
            return {"ok": True, "detail": "Memory is ready: local embeddings, group attribution, reasoning and restart checks passed.", "env_keys_written": written, "verification": verified}
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            detail = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "Memory setup was interrupted. Retry to resume; existing data is kept."
            _progress("failed", detail)
            return {"ok": False, "detail": detail}
