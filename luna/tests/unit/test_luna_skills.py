"""First-party luna/* skills are shippable: frontmatter, provenance, and deploy are in place.

Unlike the vendored humanizer, these carry no upstream pin — the contract is shape + deploy +
cache discipline (on-demand, never auto-loaded).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS = REPO_ROOT / "luna" / "skills" / "luna"


def _frontmatter(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"{skill_md} has no YAML frontmatter"
    return m.group(1)


def test_both_luna_skills_are_present_with_frontmatter():
    for name in ("local-jev", "jev-mechanics"):
        skill = SKILLS / name / "SKILL.md"
        assert skill.is_file(), f"missing {skill}"
        fm = _frontmatter(skill)
        assert f"name: {name}" in fm
        assert "description:" in fm and "metadata:" in fm
        assert 'version: "1.0.0"' in fm


def test_first_party_skills_declare_provenance():
    for name in ("local-jev", "jev-mechanics"):
        prov = (SKILLS / name / "PROVENANCE.md").read_text(encoding="utf-8")
        assert "first-party" in prov.lower()
        assert "$HERMES_HOME/skills/" in prov


def test_skills_are_deployed_but_never_auto_loaded():
    """Deploy always; injection on demand only — the cached system prompt stays clean."""
    install = (REPO_ROOT / "luna" / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert '"$PRODUCT_ROOT"/skills' in install and "$HERMES_HOME/skills" in install
    config = (REPO_ROOT / "luna" / "config" / "config.yaml.luna").read_text(encoding="utf-8")
    import yaml
    auto = yaml.safe_load(config)["skills"]["auto_load"]
    assert "local-jev" not in auto and "jev-mechanics" not in auto


def test_fallbacks_require_explicit_opt_in():
    """Fresh users never silently opt into local or paid fallback endpoints."""
    config = (REPO_ROOT / "luna" / "config" / "config.yaml.luna").read_text(encoding="utf-8")
    m = re.search(r"route:\s*\[([^\]]+)\]", config)
    assert m, "jev route list missing"
    route = [r.strip() for r in m.group(1).split(",")]
    assert route == ["zen-free"]
    assert "providers:" in config and re.search(r"^\s+local:\s*$", config, re.M)


def test_gpu_fan_guard_ships_with_the_harness():
    guard = REPO_ROOT / "luna" / "tools" / "gpu_fan_guard.py"
    assert guard.is_file()
    text = guard.read_text(encoding="utf-8")
    assert "fan1_input" in text and "kill" in text
