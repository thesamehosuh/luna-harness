#!/usr/bin/env python3
"""Install the desktop runtime into a disposable home and verify its real dashboard/CPU assets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid


def verify(archive, uv, workspace):
    install = workspace / "Clean Luna home"
    release = install / "releases/verified-fixture"
    if (release / ".ready").exists():
        release = install / ("releases/verified-fixture-" + uuid.uuid4().hex[:8])
    release.mkdir(parents=True, exist_ok=True)
    (install / ".luna-test-home").write_text("disposable\n")
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            parts = Path(member.name).parts
            if not parts or any(p in {"..", "."} for p in parts) or member.issym() or member.islnk():
                raise ValueError("Unsafe release member")
            relative = Path(*parts[1:])
            target = release / relative
            if member.isdir(): target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as data, target.open("wb") as out: shutil.copyfileobj(data, out)
                target.chmod(member.mode & 0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HERMES_", "LUNA_", "HONCHO_", "OPENAI_", "OPENROUTER_")) and not k.endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))}
    env.update(HERMES_HOME=str(install), LUNA_HOME=str(install), PYTHONUTF8="1", PYTHONIOENCODING="utf-8", XDG_CACHE_HOME=str(workspace / "cache"),
               UV_PYTHON_INSTALL_DIR=str(install / "runtime/python"), UV_CACHE_DIR=str(workspace / "uv-cache"))
    env.pop("PYTHONPATH", None); env.pop("PYTHONHOME", None); env.pop("VIRTUAL_ENV", None)
    args = [str(uv), "run", "--no-project", "--managed-python", "--python", "3.11", str(release / "luna/deploy/desktop_install.py"), "--home", str(install), "--uv", str(uv)]
    subprocess.run(args, cwd=workspace, env=env, check=True, timeout=1200)
    python = release / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python")
    pointer = json.loads((install / "current-release.json").read_text())
    assert (install / pointer["path"]).resolve() == release.resolve()
    # Import from the actual installed interpreter, outside the source checkout.
    offline = """from pathlib import Path
import os,socket
from hermes_cli.product_runtime import ROOT,code_root,executable,child_environment
from luna_core.embeddings import Embedder
from luna_core.runtime import home
assert ROOT.resolve()==code_root(home()).resolve()
assert Path(executable(home())).resolve()==Path(__import__('sys').executable).resolve()
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('network forbidden'))
model=Embedder()
vectors,count=model.vectors(['The cat sleeps on the sofa.','گربه روی مبل خوابیده است.','The database password was changed.'])
score=lambda a,b:sum(x*y for x,y in zip(a,b))
assert len(vectors[0])==384 and score(vectors[0],vectors[1])>score(vectors[0],vectors[2])+0.2
"""
    subprocess.run([str(python), "-I", "-X", "utf8", "-c", offline], cwd=workspace, env=env, check=True, timeout=90)
    token, nonce = secrets.token_hex(32), secrets.token_hex(24)
    ready = workspace / ("ready-" + nonce + ".json")
    env.update(LUNA_DESKTOP_NONCE=nonce, HERMES_DASHBOARD_SESSION_TOKEN=token, HERMES_DESKTOP_READY_FILE=str(ready))
    logs = workspace / "dashboard.log"
    with logs.open("wb") as output:
        process = subprocess.Popen([str(python), "-I", "-X", "utf8", "-m", "luna_cli.desktop"], cwd=workspace, env=env, stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 120
            while not ready.exists():
                if process.poll() is not None: raise RuntimeError("The installed dashboard exited before readiness")
                if time.monotonic() > deadline: raise RuntimeError("The installed dashboard did not become ready")
                time.sleep(0.1)
            port = json.loads(ready.read_text())["port"]
            base = f"http://127.0.0.1:{port}"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def get(path):
                with opener.open(urllib.request.Request(base + path, headers={"Authorization": "Bearer " + token}), timeout=30) as response: return json.load(response)
            def put(path, payload, revision):
                request = urllib.request.Request(base + path, data=json.dumps(payload).encode(), method="PUT",
                    headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "If-Match": revision})
                with opener.open(request, timeout=30) as response: return json.load(response)
            identity = get("/api/luna/desktop/identity")
            assert identity["nonce"] == nonce and Path(identity["home"]).resolve() == install.resolve()
            onboarding = get("/api/luna/onboarding")
            assert next(row for row in onboarding["steps"] if row["id"] == "honcho")["status"] == "todo"
            settings = get("/api/luna/memory/settings")
            assert any(row["key"] == "dialecticCadence" for row in settings["fields"])
            assert settings["status"]["enabled"] is False
            directory = get("/api/luna/people")
            assert directory["count"] == 0 and "not detailed memory" in directory["text"]
            exported = get("/api/luna/profiles/default/export")
            assert exported["format"] == "luna-profile" and exported["version"] == 1
            assert exported["config"]["agent"]["reasoning_effort"] == "medium"
            assert exported["config"]["tts"]["enabled"] is False
            assert exported["config"]["luna"]["output"]["style_filter"] is False
            assert exported["config"]["thread_sessions_per_user"] is True
            behaviour = get("/api/luna/behaviour")
            assert behaviour["conversation"]["enabled"] is True and behaviour["conversation"]["max_turns_per_burst"] == 3
            assert behaviour["conversation_status"] == {"active": [], "waiting": [], "recent": []}
            saved = put("/api/luna/behaviour", {"conversation": {"max_turns_per_burst": 2}}, behaviour["revision"])
            assert saved["behaviour"]["conversation"]["max_turns_per_burst"] == 2
            put("/api/luna/behaviour", {"conversation": behaviour["conversation"]}, saved["behaviour"]["revision"])
            character = get("/api/luna/character")
            saved = put("/api/luna/character", {"output": {"sentence_breaks": False}}, character["revision"])
            assert saved["bundle"]["output"]["sentence_breaks"] is False
            put("/api/luna/character", {"output": character["output"]}, saved["bundle"]["revision"])
            assert exported["soul"] == (release / "luna/soul/DEFAULT.md").read_text(encoding="utf-8")
            assert exported["soul"].startswith("# Companion\n")
            with opener.open(base + "/onboarding", timeout=30) as response:
                assert b"<html" in response.read().lower()
            with opener.open(base + "/docs", timeout=30) as response:
                html = response.read()
                assert b"__LUNA_DASHBOARD_APPEARANCE__" in html and b"swagger-ui" not in html
            with opener.open(base + "/login", timeout=30) as response:
                html = response.read()
                assert b"Manrope" in html and b"#17132b" in html
            with opener.open(base + "/fonts-luna/Manrope-Variable.ttf", timeout=30) as response:
                assert response.status == 200 and len(response.read()) > 10000
            # The launcher-death pipe lease must stop the backend without a PID-only kill.
            process.stdin.close()
            process.wait(timeout=20)
            return {"ok": True, "archive_sha256": hashlib.file_digest(archive.open("rb"), "sha256").hexdigest(),
                    "verified": ["isolated install", "release pointer", "installed imports", "offline multilingual embeddings", "authenticated readiness", "dashboard assets", "optional memory", "Honcho controls", "neutral new-user defaults", "portable profile export", "empty basic people directory", "group coordination controls", "sentence line-break control", "Luna documentation route", "themed sign-in and bundled fonts", "launcher lifetime lease"]}
        finally:
            if process.poll() is None: process.terminate(); process.wait(timeout=10)
            ready.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--uv", type=Path, default=Path(shutil.which("uv") or "uv"))
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--workspace", type=Path, help="resume a retained disposable test workspace")
    args = parser.parse_args()
    if args.workspace:
        result = verify(args.archive.resolve(), args.uv.resolve(), args.workspace.resolve())
    elif args.keep:
        directory = Path(tempfile.mkdtemp(prefix="luna-desktop-release-")); print("Scratch workspace:", directory, flush=True)
        result = verify(args.archive.resolve(), args.uv.resolve(), directory)
    else:
        with tempfile.TemporaryDirectory(prefix="luna-desktop-release-") as directory: result = verify(args.archive.resolve(), args.uv.resolve(), Path(directory))
    print(json.dumps(result, indent=2))
