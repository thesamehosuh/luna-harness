"""Minimal dotenv loader for the harness.

Hermes loads ``$HERMES_HOME/.env`` for the gateway process, but tests and one-off scripts need the
same values. This reads a dotenv file and fills ``os.environ`` **without overriding** variables that
are already set.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional


def parse_env_file(path: str | Path) -> Dict[str, str]:
    """Parse ``KEY=VALUE`` lines; ignores blanks, comments, and ``export`` prefixes."""
    out: Dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return out
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def load_env_file(path: str | Path, *, override: bool = False) -> int:
    """Load a dotenv file into ``os.environ``. Returns the number of vars set."""
    count = 0
    for key, value in parse_env_file(path).items():
        if override or key not in os.environ:
            os.environ[key] = value
            count += 1
    return count


def load_luna_env(home: Optional[str | Path] = None) -> int:
    """Load the harness env file, preferring ``$HERMES_HOME/.env`` then ``~/.luna/.env``.

    ``~/.hermes/.env`` is a pre-migration fallback only: it is used *instead of* the Luna files,
    never merged into them. Mixing them let stale hermes values fill gaps left by the Luna file.
    """
    candidates = []
    if home:
        candidates.append(Path(home) / ".env")
    env_home = os.getenv("HERMES_HOME")
    if env_home:
        candidates.append(Path(env_home) / ".env")
    candidates.append(Path.home() / ".luna" / ".env")
    for path in candidates:
        if path.is_file():
            return load_env_file(path)
    legacy = Path.home() / ".hermes" / ".env"
    if legacy.is_file():
        return load_env_file(legacy)
    return 0
