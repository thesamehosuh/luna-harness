"""The humanizer skill is bundled, pinned and available as an optional writing style."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "luna" / "skills" / "creative" / "humanizer"
PINNED_SHA = "9862685f575c65a8247f90369951df1b3416e3d6"


def test_skill_is_vendored_at_current_version():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert 'version: "3.0.0"' in skill, "humanizer pin is stale — see PROVENANCE.md"
    assert (SKILL_DIR / "LICENSE").is_file()


def test_provenance_pins_the_upstream_commit_and_amendment():
    prov = (SKILL_DIR / "PROVENANCE.md").read_text(encoding="utf-8")
    assert PINNED_SHA in prov
    assert "blader/humanizer" in prov
    assert "amendment" in prov.lower()


def test_skill_is_opt_in_and_framed_for_every_reply_when_selected():
    """A new character owns its voice; choosing this skill enables its every-reply guidance."""
    import yaml
    config = (REPO_ROOT / "luna" / "config" / "config.yaml.luna").read_text(encoding="utf-8")
    assert yaml.safe_load(config)["skills"]["auto_load"] == []
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "Harness note (Luna)" in skill
    assert "every outgoing message" in skill


def test_install_deploys_baked_skills():
    install = (REPO_ROOT / "luna" / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert '"$PRODUCT_ROOT"/skills' in install, "install.sh must deploy the baked skills"
    assert "$HERMES_HOME/skills" in install
