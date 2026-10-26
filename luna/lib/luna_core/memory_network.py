"""Connect only the owned Honcho stack to its worker, without changing host firewall rules."""
from pathlib import Path
import json
import platform
import socket
import subprocess

from luna_core.runtime import home
from luna_core.settings import _replace


def connection():
    try: return json.loads((home() / "honcho/.connection.json").read_text())
    except (OSError, ValueError): return {"mode": "bridge"}


def worker_url(port):
    host = "127.0.0.1" if connection().get("mode") == "loopback" else "host.docker.internal"
    return f"http://{host}:{port}/v1"


def compose_args(stack):
    path = Path(stack) / "docker-compose.connection.yaml"
    return ["-f", str(path)] if path.exists() else []


def _loopback(stack, *, database_port=0, redis_port=0):
    from luna_core.env import parse_env_file
    import yaml
    values = parse_env_file(stack / ".env")
    port = int(values["HONCHO_PORT"])
    environment = {
        "DB_CONNECTION_URI": f"postgresql+psycopg://postgres:${{POSTGRES_PASSWORD}}@127.0.0.1:{database_port}/postgres",
        "CACHE_URL": f"redis://:${{REDIS_PASSWORD}}@127.0.0.1:{redis_port}/0?suppress=true",
    }
    api = {"network_mode": "host", "environment": environment,
           "entrypoint": ["sh", "-c", f"/app/.venv/bin/python scripts/provision_db.py && exec /app/.venv/bin/fastapi run --host 127.0.0.1 --port {port} src/main.py"],
           "healthcheck": {"test": ["CMD", "/app/.venv/bin/python", "-c", f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}/health', timeout=2).read()"]}}
    value = {"services": {"api": api, "deriver": {"network_mode": "host", "environment": environment},
        "bootstrap": {"network_mode": "host", "environment": environment},
        "database": {"ports": ["127.0.0.1::5432"]}, "redis": {"ports": ["127.0.0.1::6379"]}}}
    path = stack / "docker-compose.connection.yaml"
    try:
        previous = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        previous = {}
    previous_environment = (previous.get("services", {}).get("api", {}).get("environment") or {})
    changed = any(previous_environment.get(key) != setting for key, setting in environment.items())
    if changed:
        _replace(path, yaml.safe_dump(value, sort_keys=False))
    _replace(stack / ".connection.json", json.dumps({"mode": "loopback"}))
    return changed


def configure(stack, worker, prefix):
    """Use Desktop's built-in host DNS. Native Linux can fall back to loopback-only ports."""
    from luna_core.data_ops import compose_command
    from luna_cli.onboarding import _seed_honcho_env
    from hermes_cli._subprocess_compat import windows_hide_flags
    os_name = subprocess.run([*prefix, "info", "--format", "{{.OperatingSystem}}"], capture_output=True, text=True, timeout=15, creationflags=windows_hide_flags()).stdout.lower()
    desktop = "docker desktop" in os_name or platform.system() in {"Windows", "Darwin"}
    if desktop:
        # An explicit host-gateway entry overrides Desktop's correct built-in DNS.
        _replace(stack / "docker-compose.connection.yaml", "services:\n" + "".join(f"  {service}:\n    extra_hosts: !reset []\n" for service in ("api", "deriver", "bootstrap")))
        _replace(stack / ".connection.json", json.dumps({"mode": "desktop"}))
    elif connection().get("mode") == "loopback":
        _loopback(stack)
        _seed_honcho_env(stack, refresh=True, worker=worker)
        return "loopback"
    # Probe from the actual Compose network, before schema/data operations.
    probe = ("import os,urllib.request; u=os.environ['DERIVER_MODEL_CONFIG__OVERRIDES__BASE_URL'].removesuffix('/v1')+'/health'; "
             "r=urllib.request.Request(u,headers={'Authorization':'Bearer '+os.environ['LUNA_MEMORY_API_KEY']}); "
             "urllib.request.build_opener(urllib.request.ProxyHandler({})).open(r,timeout=4).read()")
    result = subprocess.run(compose_command(stack, "run", "--rm", "--no-deps", "--entrypoint", "/app/.venv/bin/python", "api", "-c", probe), capture_output=True, timeout=120, creationflags=windows_hide_flags())
    if result.returncode == 0: return "desktop" if desktop else "bridge"
    if platform.system() != "Linux" or desktop:
        raise RuntimeError("Docker cannot reach Luna's memory worker. Allow the worker in your operating system's network permission prompt, then retry Memory setup.")
    # Native Linux host networking shares loopback without a new protocol or firewall changes.
    # Only these owned services use it. Postgres/Redis publications stay on 127.0.0.1.
    _loopback(stack)
    _seed_honcho_env(stack, refresh=True, worker=worker)
    return "loopback"


def finish_loopback(stack, run):
    database = int(run("port", "database", "5432").stdout.strip().rsplit(":", 1)[1])
    redis = int(run("port", "redis", "6379").stdout.strip().rsplit(":", 1)[1])
    return _loopback(stack, database_port=database, redis_port=redis)
