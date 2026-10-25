"""Threshold/config read-write library behind the Behaviour dashboard page.

The ``luna tune`` CLI is retired (P5 — the dashboard owns tuning). What remains is the shared
library: verdict-log reading and the comment-preserving ``luna.ambient.thresholds`` writer.
Every write is validated by re-parsing the YAML and rolled back on failure.
"""

from __future__ import annotations

import dataclasses
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from luna_core import settings

VERDICT_RE = re.compile(r"\[luna-ambient\]\s*(?:\[(?P<tag>[A-Z\-]+)\]\s*)?(?P<body>.*)")
_QFIELD_RE = re.compile(r'(?P<key>who|text|reply)="(?P<val>[^"]*)"')


def _home() -> Path:
    from luna_core.runtime import home
    return home()


def _sys_path() -> None:
    lib = _home() / "lib"
    if lib.is_dir():
        sys.path.insert(0, str(lib))
    repo_lib = Path(__file__).resolve().parents[2] / "lib"
    if repo_lib.is_dir() and str(repo_lib) not in sys.path:
        sys.path.insert(0, str(repo_lib))


def _yaml():
    import yaml

    return yaml


def _validate_document(text: str) -> Optional[str]:
    """Return an error string, or None when the document parses.

    Falls back to a structural check when PyYAML is unavailable (the slim runtime always has it; this
    keeps the operator tool importable in a bare test venv).
    """
    try:
        yaml = _yaml()
    except ImportError:
        problems = []
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "\t" in line:
                problems.append("tabs are not valid YAML indentation")
            if line.count('"') % 2 or line.count("'") % 2:
                problems.append(f"unbalanced quotes: {line.strip()[:60]}")
        return problems[0] if problems else None
    try:
        yaml.safe_load(text)
    except Exception as exc:
        return str(exc)
    return None


def config_path() -> Path:
    return _home() / "config.yaml"


def db_path() -> Path:
    return Path(os.getenv("LUNA_INDEX_DB") or (_home() / "luna-state.db"))


def agent_log() -> Path:
    return _home() / "logs" / "agent.log"


def _load_yaml(path: Path) -> dict:
    return _yaml().safe_load(settings.read(path)) or {}


def _thresholds(doc: dict) -> Dict[str, object]:
    return ((doc.get("luna") or {}).get("ambient") or {}).get("thresholds") or {}


def _defaults() -> Dict[str, object]:
    _sys_path()
    from luna_core.cascade import CascadeConfig

    return {f.name: getattr(CascadeConfig(), f.name) for f in dataclasses.fields(CascadeConfig)}


def _read_tail(path: Path, limit: int) -> List[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return lines[-limit:]


def _is_verdict_event(line: str) -> bool:
    return "luna-ambient" in line and any(
        marker in line for marker in ("verdict=", "event=settle", "event=skip", "event=said")
    )


def _thresholds_block(lines: List[str]) -> Tuple[int, int, int]:
    start = None
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)thresholds:\s*$", line)
        if not match:
            continue
        indent = len(match.group(1))
        for follow in lines[index + 1:]:
            if not follow.strip() or follow.lstrip().startswith("#"):
                continue
            if len(follow) - len(follow.lstrip()) <= indent:
                break
            if "message_min_value" in follow:
                start = index
                break
        if start is not None:
            return start, indent, index
    return -1, 0, -1


@settings.transactional
def _write_threshold(key: str, value: Optional[str]) -> Tuple[bool, str]:
    path = config_path()
    original = settings.read(path)
    lines = original.splitlines(keepends=True)
    start, indent, _ = _thresholds_block(lines)
    if start < 0:
        return False, "could not find luna.ambient.thresholds in config.yaml"
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.lstrip().startswith("#"):
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= indent:
                break
        end += 1
    pad = " " * (indent + 2)
    pattern = re.compile(rf"^{re.escape(pad)}{re.escape(key)}\s*:.*\n?$")
    for index in range(start + 1, end):
        if pattern.match(lines[index]):
            if value is None:
                del lines[index]
            else:
                lines[index] = f"{pad}{key}: {value}\n"
            break
    else:
        if value is None:
            return False, f"{key} is not set in config.yaml (nothing to reset)"
        lines.insert(end, f"{pad}{key}: {value}\n")
    error = _validate_document("".join(lines))
    if error:
        return False, f"refusing to write invalid YAML: {error}"
    settings.write(path, "".join(lines))
    return True, f"{key} {'removed' if value is None else 'set to ' + value}"
