#!/usr/bin/env python3
"""Run the synthetic ambient/Jev audit regression suite (no live model or chat calls)."""
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q",
        "luna/tests/component/test_ambient_jev_regressions.py", *sys.argv[1:]], cwd=root))
