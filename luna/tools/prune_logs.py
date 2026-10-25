from __future__ import annotations

import argparse
import os
import time
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

DEFAULT_FILES = ("agent.log", "errors.log", "gateway.log", "gui.log")


def _home(explicit: str | None = None) -> Path:
    return Path(explicit or os.getenv("HERMES_HOME") or str(Path.home() / ".luna")).expanduser()


def _config_value(home: Path, key: str, default):
    try:
        from luna_core import config_read

        return config_read.section("luna", *key.split("."), default=default)
    except Exception:
        return default


def _retention_days(home: Path, explicit: int | None) -> int:
    if explicit is not None:
        return max(0, explicit)
    raw = os.getenv("LUNA_LOG_RETENTION_DAYS")
    if raw is not None and raw.strip():
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    value = _config_value(home, "logs.retention_days", 1)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 1


def _files(home: Path, explicit: Iterable[str] | None) -> tuple[str, ...]:
    if explicit:
        values = explicit
    else:
        raw = os.getenv("LUNA_LOG_RETENTION_FILES")
        if raw is not None and raw.strip():
            values = [part.strip() for part in raw.split(",") if part.strip()]
        else:
            configured = _config_value(home, "logs.files", None)
            values = configured if isinstance(configured, list) else DEFAULT_FILES
    result: list[str] = []
    for value in values:
        name = str(value).strip()
        if not name or Path(name).name != name or not name.endswith(".log"):
            continue
        if name not in result:
            result.append(name)
    return tuple(result)


def _truncate(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        with path.open("r+b", buffering=0) as handle:
            handle.seek(0)
            handle.truncate(0)
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except OSError:
        return False


def prune_logs(home: str | Path | None = None, *, retention_days: int | None = None,
               files: Iterable[str] | None = None, now: float | None = None) -> dict[str, int]:
    root = _home(str(home) if home is not None else None)
    days = _retention_days(root, retention_days)
    if days <= 0:
        return {"truncated": 0, "removed": 0, "failed": 0}
    log_dir = root / "logs"
    if not log_dir.is_dir():
        return {"truncated": 0, "removed": 0, "failed": 0}
    cutoff = (time.time() if now is None else now) - days * 86400
    truncated = 0
    removed = 0
    failed = 0
    for name in _files(root, files):
        active = log_dir / name
        if active.exists():
            if _truncate(active):
                truncated += 1
            else:
                failed += 1
        for rotated in log_dir.glob(f"{name}.*"):
            try:
                if rotated.is_symlink() or not rotated.is_file():
                    continue
                if rotated.stat().st_mtime < cutoff:
                    rotated.unlink()
                    removed += 1
            except OSError:
                failed += 1
    return {"truncated": truncated, "removed": removed, "failed": failed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home")
    parser.add_argument("--retention-days", type=int)
    parser.add_argument("--file", action="append", dest="files")
    args = parser.parse_args(argv)
    result = prune_logs(args.home, retention_days=args.retention_days, files=args.files)
    print(
        f"truncated={result['truncated']} removed={result['removed']} failed={result['failed']}"
    )
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
