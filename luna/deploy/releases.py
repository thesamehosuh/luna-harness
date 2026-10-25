"""Stage complete immutable runtimes and publish/roll back their current pointer."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import shutil
import sys
import uuid
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assemble import assemble

STATE = {"plugins", "skills", "skins", "bin", "config.yaml", "SOUL.md", "PEOPLE.md", "honcho.json", "AGENTS.md"}


def pointer(path, target):
    temporary = path.with_name("." + path.name + "-" + uuid.uuid4().hex)
    temporary.symlink_to(target)
    os.replace(temporary, path)


def stage(source, home):
    home.mkdir(parents=True, exist_ok=True)
    releases = home / "releases"
    releases.mkdir(exist_ok=True)
    target = releases / uuid.uuid4().hex
    try:
        assemble(source, target)
        (target / ".luna-state-home").write_text(str(home.resolve()))
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def publish(home, release):
    from hermes_cli._file_lock import acquire
    with (home / ".release.lock").open("a+") as lock:
        acquire(lock)
        return _publish(home, release)


def _snapshot_state(home):
    """Automatic local migration checkpoint. Full memory backups remain a separate operation."""
    directory = home / "backups/luna"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = "upgrade-local-" + uuid.uuid4().hex + ".tar.gz"
    with tempfile.TemporaryDirectory(prefix="luna-upgrade-state-") as temporary:
        staging = Path(temporary)
        databases = [*home.glob("*.db"), *(home / "profiles").rglob("*.db")]
        files = [home / name for name in ("config.yaml", "SOUL.md", "PEOPLE.md", "honcho.json", ".env", "auth.json")]
        for profile in (home / "profiles").glob("*"):
            files.extend(profile / name for name in ("config.yaml", "SOUL.md", "PEOPLE.md", "honcho.json", ".env", "auth.json"))
        for source in databases + files:
            if not source.is_file() or source.is_symlink():
                continue
            target = staging / source.relative_to(home)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix == ".db":
                with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
                    with closing(sqlite3.connect(target)) as dst:
                        src.backup(dst)
                        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise ValueError("Upgrade state snapshot failed integrity verification")
            else:
                shutil.copy2(source, target)
        (staging / "backup.json").write_text(json.dumps({"format": 1, "kind": "upgrade-local", "honcho": "not included; no remote migration", "at": datetime.now(timezone.utc).isoformat()}))
        target = directory / name
        with tarfile.open(target, "w:gz") as archive:
            for child in staging.iterdir():
                archive.add(child, arcname=child.name)
        target.chmod(0o600)


def _publish(home, release):
    release = release.resolve()
    if release.parent != (home / "releases").resolve() or not (release / ".luna-assemble-manifest.json").is_file():
        raise ValueError("not a staged release owned by this installation")
    if not (release / ".ready").is_file():
        raise ValueError("release dependencies and checks must pass before publication")
    previous = (home / "current").resolve() if (home / "current").is_symlink() else None
    # Compatibility links are stable across later upgrades; state never lives behind current.
    legacy = home / "legacy-before-releases"
    # Preflight every legacy conversion before changing any compatibility link.
    for path in release.iterdir():
        if path.name in STATE or path.name.startswith("."):
            continue
        link = home / path.name
        if link.is_symlink() and os.readlink(link) == str(Path("current") / path.name):
            continue
        if (link.exists() or link.is_symlink()) and ((legacy / path.name).exists() or (legacy / path.name).is_symlink()):
            raise ValueError(f"legacy backup already exists for {path.name}")
    if previous:
        _snapshot_state(home)
    for path in release.iterdir():
        if path.name in STATE or path.name.startswith("."):
            continue
        link = home / path.name
        expected = Path("current") / path.name
        if link.is_symlink() and os.readlink(link) == str(expected):
            continue
        if link.exists() or link.is_symlink():
            legacy.mkdir(exist_ok=True)
            backup = legacy / path.name
            if backup.exists() or backup.is_symlink():
                raise ValueError(f"legacy backup already exists for {path.name}")
            link.rename(backup)
        pointer(link, expected)
    # Engine and companion plugins have separate discovery paths, both anchored in this release.
    plugins = home / "plugins"
    plugins.mkdir(exist_ok=True)
    for parent, relative in [(release / "plugins", "../current/plugins"), (release / "luna/plugins", "../current/luna/plugins")]:
        if not parent.exists():
            continue
        for path in parent.iterdir():
            link = plugins / path.name
            if link.exists() and not link.is_symlink():
                continue  # operator-installed plugins belong to state
            pointer(link, Path(relative) / path.name)
    if previous:
        pointer(home / "previous", previous.relative_to(home))
    pointer(home / "current", release.relative_to(home))
    shutil.copy2(release / ".luna-assemble-manifest.json", home / ".luna-assemble-manifest.json")
    return release


def rollback(home):
    if (home / "current-release.json").is_file():
        from luna_core.release_control import rollback as portable_rollback
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        token = set_hermes_home_override(home)
        try:
            return portable_rollback()
        finally:
            reset_hermes_home_override(token)
    previous = home / "previous"
    if not previous.is_symlink() or not (previous / ".ready").exists():
        raise ValueError("No verified previous release is available")
    manifest = previous / "luna-release.json"
    state = home / "luna-state.db"
    if state.exists():
        with closing(sqlite3.connect(state.as_uri() + "?mode=ro", uri=True)) as conn:
            version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        compatible = json.loads(manifest.read_text()).get("data", {}).get("supported_luna_schemas", []) if manifest.exists() else []
        if version and int(version[0]) not in compatible:
            raise ValueError("Previous release does not declare support for this data schema. Restore its compatible state backup first.")
    return publish(home, previous.resolve())


if __name__ == "__main__":
    command, source, target = sys.argv[1:]
    if command == "stage":
        print(stage(Path(source).resolve(), Path(target).resolve()))
    elif command == "publish":
        print(publish(Path(target).resolve(), Path(source).resolve()))
    elif command == "rollback":
        print(rollback(Path(target).resolve()))
    else:
        raise SystemExit("unknown release operation")
