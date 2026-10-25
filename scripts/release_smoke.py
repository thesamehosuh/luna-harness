"""Install an actual release in isolation, remove its unpacked source, and probe the dashboard."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

PROBE = r'''
import importlib.util, json, os, re, shlex
from pathlib import Path
import hermes_cli, luna_core
from fastapi.testclient import TestClient
from hermes_cli import web_server
from luna_cli import onboarding
home = Path(os.environ["HERMES_HOME"]).resolve()
for module in (hermes_cli, luna_core):
    assert Path(module.__file__).resolve().is_relative_to(home), module.__file__
onboarding._probe_health = lambda *args, **kwargs: False
client = TestClient(web_server.app)
response = client.get("/")
assert response.status_code == 200, response.text
for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', response.text):
    assert client.get(asset).status_code == 200, asset
assert client.get("/api/luna/onboarding").status_code in (401, 403)
headers = {"X-Hermes-Session-Token": web_server._active_session_token()}
steps = client.get("/api/luna/onboarding", headers=headers)
assert steps.status_code == 200, steps.text
assert steps.json()["complete"] is False
from luna_core import opencode_install
from luna_core.opencode_aux import OpenCodeAuxClient
from hermes_cli.runtime_provider import resolve_runtime_provider
assert Path(opencode_install.__file__).with_name("OPENCODE_NOTICES.txt").is_file()
assert len(opencode_install.RELEASES["targets"]) == 8
runtime = resolve_runtime_provider(requested="opencode-engine")
assert runtime["base_url"] == "opencode://local" and runtime["api_key"] == "no-key-required"
assert OpenCodeAuxClient("opencode/big-pickle")._hermes_aux_effective_provider == "opencode-engine"
assert client.get("/api/luna/opencode", headers=headers).status_code == 200
for name in ("luna-room", "luna-memory", "luna-ambient", "luna-logger"):
    plugin = home / "plugins" / name
    assert plugin.resolve().is_relative_to(home), plugin
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), plugin / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
from acp_adapter import edit_approval
from hermes_cli.update_contract import evaluate_update_admission
assert evaluate_update_admission(home).code == "luna-release"
units = Path(os.environ["XDG_CONFIG_HOME"]) / "systemd/user"
for path in units.glob("luna-*.service"):
    command = next(line.removeprefix("ExecStart=") for line in path.read_text().splitlines() if line.startswith("ExecStart="))
    arguments = shlex.split(command)
    assert arguments[0] == str(home / "venv/bin/python"), command
    assert Path(arguments[1]).is_relative_to(home), command
assert len(list(units.glob("hermes-gateway*.service"))) == 1
print(json.dumps({"installed_imports": True, "dashboard_and_assets": True,
                  "authenticated_companion_api": True, "plugins": 4,
                  "source_removed": True, "upstream_update_blocked": True,
                  "service_definitions": True, "native_opencode_packaged": True}))
'''


def smoke(artifact: Path, *, keep=False) -> dict:
    python = sys.executable
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        python = subprocess.check_output(["uv", "python", "find", "3.11"], text=True).strip()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("LUNA_", "HERMES_", "PYTHONPATH", "PYTHONHOME"))
           and not key.endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))}
    public_cache = Path(tempfile.gettempdir()) / f"luna-release-download-cache-{os.getuid()}"
    env.setdefault("XDG_CACHE_HOME", str(public_cache))
    env.setdefault("UV_CACHE_DIR", str(Path.home() / ".cache/uv"))
    workspace = nullcontext(tempfile.mkdtemp(prefix="luna-release-smoke-")) if keep else tempfile.TemporaryDirectory(prefix="luna-release-smoke-")
    with workspace as tmp:
        root = Path(tmp)
        if keep:
            print(f"Smoke workspace: {root}", flush=True)
        unpacked, runtime, user = root / "unpacked", root / "runtime with spaces", root / "user"
        user.mkdir()
        with tarfile.open(artifact) as tar:
            # Build output is trusted, but refuse paths outside the unpack directory regardless.
            for member in tar.getmembers():
                path = (unpacked / member.name).resolve()
                if not path.is_relative_to(unpacked.resolve()) or member.islnk():
                    raise ValueError(f"unsafe archive member: {member.name}")
            tar.extractall(unpacked, filter="data")
        release = next(p for p in unpacked.iterdir() if p.is_dir())
        fakebin = root / "fakebin"
        fakebin.mkdir()
        systemctl = fakebin / "systemctl"
        systemctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$LUNA_TEST_SYSTEMCTL_LOG"\n')
        systemctl.chmod(0o755)
        env.update(HOME=str(user), PYTHON=python, SKIP_SYSTEMD="0", BUILD_DASHBOARD="0",
                   XDG_CONFIG_HOME=str(user / ".config"), PATH=str(fakebin) + os.pathsep + env.get("PATH", ""),
                   LUNA_TEST_SYSTEMCTL_LOG=str(root / "systemctl.log"))
        result = subprocess.run(["bash", str(release / "install.sh"), str(runtime)], cwd=root,
                                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(result.stdout)
        assert (root / "systemctl.log").read_text().splitlines() == ["--user daemon-reload"]
        shutil.rmtree(unpacked)
        chat_probe = root / "verify_dashboard_chat.py"
        shutil.copy2(Path(__file__).with_name("verify_dashboard_chat.py"), chat_probe)
        env.update(HERMES_HOME=str(runtime), LUNA_HOME=str(runtime))
        env["LUNA_TEST_CODE_ROOT"] = str((runtime / "current").resolve())
        result = subprocess.run([str(runtime / "venv/bin/python"), "-I", "-c", PROBE],
                                cwd=root, env=env, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        report = json.loads(result.stdout.strip().splitlines()[-1])
        chat = subprocess.run([str(runtime / "venv/bin/python"), "-I", str(chat_probe)],
                              cwd=root, env=env, capture_output=True, text=True, timeout=120)
        if chat.returncode:
            raise RuntimeError(chat.stdout + chat.stderr)
        report["actual_dashboard_chat"] = json.loads(chat.stdout[chat.stdout.index("{"):])
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--keep", action="store_true", help="keep the isolated workspace for diagnosis")
    args = parser.parse_args()
    print(json.dumps(smoke(args.artifact.resolve(), keep=args.keep), indent=2))
