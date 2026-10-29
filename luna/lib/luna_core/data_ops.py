"""Owned data inventory, SQLite-consistent local backups and stopped-runtime restores."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import uuid

from luna_core.runtime import home

TREES = ("memories", "sessions", "skills", "cron", "profiles", "skins", "opencode")
FILES = ("config.yaml", "SOUL.md", "PEOPLE.md", "honcho.json", ".env", "auth.json", "gateway.json")
INVENTORY = [
    {"store": "Room index and delivery ledger", "path": "luna-state.db", "retention": "luna.data.retention_days", "backup": "SQLite backup API"},
    {"store": "Transcripts", "path": "state.db, sessions/", "retention": "Observed messages by age; ended sessions by inactivity. Active sessions remain until ended.", "backup": "SQLite backup API + files"},
    {"store": "Native history", "path": "opencode/sessions/; legacy opencode/{data,home,cache,state}/", "retention": "Session creation age; legacy stores by last write; active workers are deferred", "backup": "SQLite backup API + files; stop workers for a single point-in-time snapshot"},
    {"store": "Image snapshots", "path": "opencode/attachments/", "retention": "Last attachment use", "backup": "Files"},
    {"store": "Honcho raw sources", "path": "Managed private Postgres", "retention": "Expired sources already derived; pending work is retained and reported", "backup": "pg_dump"},
    {"store": "Derived memory", "path": "Honcho conclusions, memories/", "retention": "Persistent until explicitly deleted", "backup": "pg_dump + files"},
    {"store": "Identity", "path": "luna-state.db", "retention": "Persistent until explicitly deleted", "backup": "SQLite backup API"},
    {"store": "Basic people directory", "path": "PEOPLE.md", "retention": "Persistent; names, aliases, pronouns and short roles only", "backup": "Private data backup; excluded from portable profiles"},
    {"store": "Group file memory", "path": "memories/groups/*/MEMORY.md", "retention": "Persistent, isolated by group and topic", "backup": "Private data backup; excluded from portable profiles"},
    {"store": "Logs", "path": "logs/", "retention": "luna.logging.*", "backup": "Excluded; operational data"},
    {"store": "Backups", "path": "backups/luna/", "retention": "luna.data.backup_days", "backup": "Download archive"},
]


def compose_command(stack, *args):
    # Same project identity as onboarding. Never expose the database port or passwords.
    import hashlib
    project = "luna-" + hashlib.sha256(str(stack.parent.resolve()).encode()).hexdigest()[:12]
    from luna_core.docker_setup import command
    from luna_core.memory_network import compose_args
    return [*command(), "compose", "--project-name", project, "--env-file", str(stack / ".env"), "-f", str(stack / "docker-compose.yml"), *compose_args(stack), *args]


def require_stopped():
    from gateway.status import is_gateway_running
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    roots = [home(), *[path for path in (home() / "profiles").glob("*") if path.is_dir()]]
    for root in roots:
        token = set_hermes_home_override(root)
        try:
            if is_gateway_running(cleanup_stale=False):
                raise ValueError("Stop the affected profile gateways in System before restoring data")
        finally:
            reset_hermes_home_override(token)
    from luna_core.native_resources import idle
    for root in roots:
        sessions = {path.name for path in (root / "opencode/sessions").glob("*")}
        sessions.update(path.stem for path in (root / "opencode/leases").glob("*.lock"))
        for session in sessions:
            handle = idle(root / "opencode", session)
            if handle is None:
                raise ValueError("A native worker is still running. Wait for it to finish before restoring data")
            handle.close()


def _restore_postgres(dump, root):
    command = compose_command(root / "honcho", "exec", "-T", "database", "sh", "-c", 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec pg_restore -U postgres -d postgres --clean --if-exists --single-transaction')
    with dump.open("rb") as source:
        result = subprocess.run(command, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    if result.returncode:
        raise RuntimeError("Memory restore failed")


def _publish_local(stage, root):
    """Retain originals on the state filesystem until every replacement succeeds."""
    originals = stage.parent / "originals"
    originals.mkdir()
    changed = []
    try:
        for child in stage.iterdir():
            if child.name in {"backup.json", "honcho.dump"}:
                continue
            target = root / child.name
            if target.is_symlink():
                raise ValueError("Cannot restore through a state symlink")
            previous = originals / child.name
            if target.exists():
                os.replace(target, previous)
            changed.append((target, previous))
            os.replace(child, target)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(target) + suffix)
                if sidecar.exists():
                    os.replace(sidecar, originals / sidecar.name)
    except BaseException:
        for target, previous in reversed(changed):
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
            if previous.exists():
                os.replace(previous, target)
            for suffix in ("-wal", "-shm"):
                sidecar = originals / (target.name + suffix)
                if sidecar.exists():
                    os.replace(sidecar, Path(str(target) + suffix))
        raise


def _copy(source, target):
    if source.is_symlink():
        return
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            if child.name not in {"venv", "bin", "cache", "__pycache__"} and not child.name.endswith(("-wal", "-shm")):
                _copy(child, target / child.name)
    elif source.suffix in {".db", ".sqlite", ".sqlite3"}:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("Database backup integrity check failed")
    else:
        shutil.copy2(source, target)


def backup():
    root = home()
    directory = root / "backups/luna"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8] + ".tar.gz"
    report = {"format": 1, "at": datetime.now(timezone.utc).isoformat(), "honcho": "not managed"}
    with tempfile.TemporaryDirectory(prefix="luna-backup-") as temporary:
        stage = Path(temporary)
        for name_on_disk in (*FILES, *TREES, *[p.name for p in root.glob("*.db")]):
            source = root / name_on_disk
            if source.exists():
                _copy(source, stage / name_on_disk)
        stack = root / "honcho"
        if (stack / "docker-compose.yml").exists():
            command = compose_command(stack, "exec", "-T", "database", "sh", "-c", 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec pg_dump -U postgres -d postgres -Fc')
            with (stage / "honcho.dump").open("wb") as output:
                result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, timeout=120)
            if result.returncode:
                raise RuntimeError("Managed memory backup failed; no complete backup was published")
            report["honcho"] = "pg_dump"
        (stage / "backup.json").write_text(json.dumps(report))
        target = directory / name
        temporary_archive = target.with_suffix(".partial")
        try:
            with tarfile.open(temporary_archive, "w:gz") as archive:
                for child in stage.iterdir():
                    archive.add(child, arcname=child.name, recursive=True)
            temporary_archive.chmod(0o600)
            os.replace(temporary_archive, target)
        finally:
            temporary_archive.unlink(missing_ok=True)
    return {"name": name, "bytes": target.stat().st_size, **report}


def restore(name):
    require_stopped()
    root = home()
    if Path(name).name != name or not name.endswith(".tar.gz"):
        raise ValueError("Choose a backup from this profile")
    path = root / "backups/luna" / name
    # Recoverability before changing state; never restore the backup directory over itself.
    safety = backup()
    with tempfile.TemporaryDirectory(prefix=".luna-restore-", dir=root) as temporary:
        stage = Path(temporary) / "incoming"
        stage.mkdir()
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if not (stage / member.name).resolve().is_relative_to(stage) or member.issym() or member.islnk():
                    raise ValueError("Unsafe backup path")
                top = Path(member.name).parts[0]
                if top not in {*FILES, *TREES, "backup.json", "honcho.dump"} and not (top.endswith(".db") and len(Path(top).parts) == 1):
                    raise ValueError("Unsupported backup contents")
            archive.extractall(stage, filter="data")
        if json.loads((stage / "backup.json").read_text()).get("format") != 1:
            raise ValueError("Unsupported backup format")
        dump = stage / "honcho.dump"
        if dump.exists():
            _restore_postgres(dump, root)
        try:
            _publish_local(stage, root)
        except BaseException:
            if dump.exists():
                recovery = Path(temporary) / "safety.dump"
                with tarfile.open(root / "backups/luna" / safety["name"]) as archive:
                    source = archive.extractfile("honcho.dump")
                    if source is None:
                        raise RuntimeError("Local restore failed; restore the saved safety backup to recover managed memory")
                    with source, recovery.open("wb") as output:
                        shutil.copyfileobj(source, output)
                _restore_postgres(recovery, root)
            raise
    return {"ok": True, "safety_backup": safety["name"], "restart_required": True}
