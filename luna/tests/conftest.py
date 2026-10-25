"""Shared pytest configuration for the Luna harness tests.

Puts the repo root and the shared ``luna/lib`` library on ``sys.path`` so tests can import
``luna_core`` (and, where needed, upstream hermes modules from the checkout).
"""

from __future__ import annotations

import os
import tempfile
import atexit
import sys
from pathlib import Path

import pytest

_session_home = tempfile.TemporaryDirectory(prefix="luna-test-session-")
os.environ["HERMES_HOME"] = _session_home.name
atexit.register(_session_home.cleanup)

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "luna" / "lib"

for entry in (REPO_ROOT, LIB_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


# Environment isolation for the whole suite. Production code reads a documented set of LUNA_*
# overrides that redirect the databases it reads *and prunes*; without clearing them, a
# developer (or CI) that exports e.g. LUNA_INDEX_DB would have the retention tests delete rows
# from that real database. Snapshot and restore rather than delete, so a test can still set them.
_LUNA_ENV_PREFIXES = ("LUNA_",)


@pytest.fixture(autouse=True)
def _isolate_luna_env(monkeypatch, tmp_path):
    snapshot = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(_LUNA_ENV_PREFIXES)
    }
    for key in snapshot:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "isolated-engine-home"))
    yield
    # monkeypatch restores anything a test set; nothing else to do.
