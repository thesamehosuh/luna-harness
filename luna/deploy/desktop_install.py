"""Verified-release installer invoked by the Rust launcher, never a user's shell.

Runs at the final immutable path so Python environments remain relocatable within
the installation contract. Publication is one atomic JSON replacement on every OS.
No PATH changes, service registration, Docker setup or gateway starts occur here.
"""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".luna-publish-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def install(release, home, uv):
    home = home.resolve()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    sys.path.insert(0, str(release.resolve()))
    from hermes_cli._file_lock import acquire
    with (home / ".release.lock").open("a+") as lock:
        acquire(lock)
        return _install(release, home, uv)


def _install(release, home, uv):
    release, home = release.resolve(), home.resolve()
    if release.parent != home / "releases":
        raise ValueError("Release must be staged inside this installation's releases directory")
    if not (release / ".luna-assemble-manifest.json").is_file():
        raise ValueError("Not an assembled Luna release")
    if not (release / "hermes_cli/web_dist/index.html").is_file():
        raise ValueError("This release is missing its dashboard")
    env = dict(os.environ, HERMES_HOME=str(home), LUNA_HOME=str(home),
               UV_PYTHON_INSTALL_DIR=str(home / "runtime/python"),
               UV_CACHE_DIR=str(home / "cache/uv"), UV_PYTHON_PREFERENCE="only-managed",
               UV_PROJECT_ENVIRONMENT=str(release / "venv"),
               PYTHONPATH=os.pathsep.join((str(release), str(release / "luna/lib"))))
    python = release / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python")
    def run(*args):
        subprocess.run(list(map(str, args)), cwd=release, env=env, check=True, creationflags=0x08000000 if os.name == "nt" else 0)
    marker = home / "current-release.json"
    try:
        prior_record = json.loads(marker.read_text()) if marker.is_file() else {}
        old = (home / prior_record["path"]).resolve() if prior_record else (home / "current").resolve()
        if old.parent != home / "releases": old = home / "no-valid-previous-release"
    except (OSError, ValueError, KeyError, TypeError):
        prior_record = {}
        old = home / "no-valid-previous-release"
    if (old / ".ready").is_file():
        old_python = old / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python")
        run(old_python, "-I", "-c", "from luna_core.data_ops import require_stopped; require_stopped()")
    print("LUNA_STAGE dependencies", flush=True)
    run(uv, "sync", "--project", release, "--python", "3.11", "--frozen", "--extra", "luna", "--no-dev", "--inexact")
    run(uv, "pip", "install", "--python", python, "--no-deps", "-e", release / "luna/lib")
    print("LUNA_STAGE chat-runtime", flush=True)
    run(python, release / "luna/deploy/node_runtime.py", release)
    if os.name == "nt":
        print("LUNA_STAGE native-tools", flush=True)
        script = release / "luna/deploy/windows-bootstrap.ps1"
        env["LUNA_BOOTSTRAP_SCOPED"] = "1"
        run("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
            "-Stage", "git", "-NonInteractive", "-Json", "-HermesHome", home, "-InstallDir", release)
    run(python, "-I", "-c", "import luna_core, luna_cli, gateway, model_tools, hermes_cli.web_server")
    (release / ".luna-state-home").write_text(str(home), encoding="utf-8")
    print("LUNA_STAGE personal-home", flush=True)
    # Seed through the existing product implementation, retaining existing settings.
    run(python, "-c", "from hermes_cli.product_runtime import seed_home, default_soul; from pathlib import Path; import os; h=Path(os.environ['HERMES_HOME']); seed_home(h); p=h/'SOUL.md'; p.write_text(default_soul(), encoding='utf-8') if not p.exists() else None")
    stack = home / "honcho"
    if not stack.exists():
        shutil.copytree(release / "luna/honcho", stack)
    # This also protects repair when the old pointer is damaged or absent.
    run(python, "-I", "-c", "from luna_core.data_ops import require_stopped; require_stopped()")
    if (old / ".ready").is_file():
        # Recheck after downloads, since the owner could have started the old gateway meanwhile.
        run(old_python, "-I", "-c", "from luna_core.data_ops import require_stopped; require_stopped()")
        from releases import _snapshot_state
        _snapshot_state(home)
    (release / ".ready").write_text("verified\n", encoding="utf-8")
    if prior_record and (old / ".ready").is_file():
        prior = prior_record
        previous = {key: prior[key] for key in ("format", "path", "version") if key in prior}
        atomic_json(home / "previous-release.json", previous)
    elif (home / "current").is_dir():
        previous = {"format": 1, "path": str((home / 'current').resolve().relative_to(home))}
        atomic_json(home / "previous-release.json", previous)
    else:
        previous = None
    if marker.exists() and not prior_record:
        shutil.copy2(marker, home / (".invalid-release-pointer-" + release.name + ".json"))
    atomic_json(marker, {"format": 1, "path": str(release.relative_to(home)),
                         "version": json.loads((release / "luna-release.json").read_text())["version"], "previous": previous})
    print("LUNA_STAGE ready", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    args = parser.parse_args()
    install(Path(__file__).resolve().parents[2], args.home, args.uv)
