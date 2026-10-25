"""Contract test: assemble.sh must not exclude a package pyproject ships.

The slim runtime is an editable install of the same project pyproject.toml describes, so a
top-level package omitted from the runtime is invisible to the import system — and every module
that imports it fails at runtime. This bit once: excluding ``acp_adapter`` made model_tools'
edit-approval guard raise, which fail-closes and blocked every ``write_file``/``patch`` with
"Edit approval denied: approval guard failed".
"""

from __future__ import annotations

import re
import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ASSEMBLE = REPO_ROOT / "luna" / "deploy" / "assemble.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _excluded_top_level_dirs() -> set[str]:
    """Top-level directory names assemble.sh excludes (``*.pyc``/``AGENTS.md`` style entries out)."""
    return runpy.run_path(str(ASSEMBLE))["EXCLUDED_ROOTS"]


def _declared_packages() -> set[str]:
    """Top-level package names from ``[tool.setuptools.packages.find] include``."""
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(
        r"\[tool\.setuptools\.packages\.find\]\s*\n(?:[^\[]*\n)*?include\s*=\s*\[([^\]]*)\]",
        text,
    )
    assert match, "pyproject.toml: packages.find include not found"
    entries = re.findall(r'"([^"]+)"', match.group(1))
    assert entries, "pyproject.toml: packages.find include is empty"
    return {entry[:-2] if entry.endswith(".*") else entry for entry in entries}


def test_no_declared_package_is_excluded_from_the_runtime():
    excluded = _excluded_top_level_dirs()
    declared = _declared_packages()
    leaked = sorted(excluded & declared)
    assert not leaked, (
        "assemble.sh excludes a pyproject-declared package from the runtime: "
        f"{leaked}. Importing it fails at runtime — the keep-set must ship it."
    )


def test_edit_approval_module_exists_for_the_write_guard():
    # model_tools._pre_dispatch_guards fail-closes write_file/patch when this import raises.
    assert (REPO_ROOT / "acp_adapter" / "edit_approval.py").is_file()
