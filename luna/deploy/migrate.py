"""Snapshot a Hermes/Luna home into a separate trial home. Never change the source."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

FILES = (".env", "config.yaml", "SOUL.md", "honcho.json", "auth.json", "gateway.json")
DIRECTORIES = ("memories", "sessions", "skills", "plugins", "cron", "profiles", "skins")


def snapshot(source: Path, destination: Path, *, dry_run: bool = False) -> dict:
    source, destination = source.expanduser().resolve(), destination.expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"source missing: {source}")
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("source and destination must be separate, non-overlapping directories")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("destination must be empty; migrate before installing into the trial home")
    report = {"format": 1, "databases": {}, "files": [], "directories": []}
    databases = sorted(source.glob("*.db"))
    report["files"] = [name for name in FILES if (source / name).is_file()]
    report["directories"] = [name for name in DIRECTORIES if (source / name).is_dir()]
    if dry_run:
        report["databases"] = {p.name: "would snapshot" for p in databases}
        return report
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".luna-migration-", dir=destination.parent))
    try:
        for path in databases:
            # The backup API includes committed WAL contents consistently. Verify the snapshot,
            # never compare with a live source a second time (it may have advanced already).
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as src:
                with closing(sqlite3.connect(staging / path.name)) as dst:
                    src.backup(dst)
                    if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise ValueError(f"SQLite integrity check failed: {path.name}")
                    counts = {}
                    tables = [row[0] for row in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                    for table in tables:
                        quoted = table.replace('"', '""')
                        counts[table] = dst.execute(f'SELECT count(*) FROM "{quoted}"').fetchone()[0]
                    report["databases"][path.name] = counts
        for name in report["files"]:
            # Materialize links: a trial .env or persona must not write through to the live one.
            shutil.copy2(source / name, staging / name)
            os.chmod(staging / name, 0o600)
        for name in report["directories"]:
            shutil.copytree(source / name, staging / name, symlinks=False,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "venv", "node_modules", "*.db", "*-wal", "*-shm"))
            for database in (source / name).rglob("*.db"):
                relative = database.relative_to(source)
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as src:
                    with closing(sqlite3.connect(target)) as dst:
                        src.backup(dst)
                        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise ValueError(f"SQLite integrity check failed: {relative}")
                report["databases"][str(relative)] = "verified SQLite backup"
        (staging / ".luna-migration.json").write_text(json.dumps(report, indent=2) + "\n")
        if destination.exists():
            destination.rmdir()  # checked empty above; refuses if another process put anything here
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        report = snapshot(args.source, args.destination, dry_run=args.dry_run)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"migration: {exc}\n")
    print(json.dumps(report, indent=2))
    print("Source unchanged. This copies local history, identity, settings and credentials.")
    print("Honcho's Postgres memory stays in its existing stack; this is not a Postgres backup.")
    print("Keep the trial gateway stopped while the old gateway uses the same Telegram token.")


if __name__ == "__main__":
    main()
