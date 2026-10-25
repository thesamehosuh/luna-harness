"""Smoke test: the Luna overlay scaffold exists.

Real coverage lands in the unit/component/contract/replay tiers (see ``PRODUCT_PLAN.md`` §7).
This test only proves the product layout is wired up so ``scripts/test.sh`` runs green from the
start.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_overlay_files_present() -> None:
    assert (REPO_ROOT / "AGENTS.md").is_file()
    assert (REPO_ROOT / "NOTICE").is_file()
    assert (REPO_ROOT / "PRODUCT_PLAN.md").is_file()
    assert (REPO_ROOT / "luna" / "README.md").is_file()


def test_overlay_dirs_present() -> None:
    for rel in (
        "luna/config",
        "luna/docs",
        "luna/plugins/luna-room",
        "luna/plugins/luna-memory",
        "luna/plugins/luna-ambient",
        "luna/plugins/luna-logger",
        "luna/tests/unit",
        "luna/tests/component",
        "luna/tests/contract",
        "luna/tests/replay",
        "luna/tests/fixtures",
    ):
        assert (REPO_ROOT / rel).is_dir(), f"missing {rel}"
