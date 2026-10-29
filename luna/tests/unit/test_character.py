"""Structured persona + voice shaping (PRODUCT_PLAN P4): SOUL sections, hard limits, preview,
skins, skills — all against a scratch home, no network."""

from __future__ import annotations

import pytest
import yaml

from luna_cli import character

SOUL = """\
# Luna

I'm the group friend who happens to be an AI.

## Who I am

I feel things.

## Voice

- Talk like a person, not a product.

## Custom Extra

A user-added section survives.

## Hard rules

Never leak secrets.

---

She/her.
"""


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "SOUL.md").write_text(SOUL, encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        "# keep me\nluna:\n  output:\n    emoji_filter: true\n    allowed_emoji: [\"😭\"]\n"
        "display:\n  skin: default\nskills:\n  auto_load:\n    - humanizer\n",
        encoding="utf-8",
    )
    return tmp_path


# ── SOUL sections ────────────────────────────────────────────────────────────────────────────────


def test_parse_and_render_round_trip():
    parsed = character.parse_soul(SOUL)
    assert parsed["title"] == "Luna"
    assert "group friend" in parsed["intro"]
    assert [s["title"] for s in parsed["sections"]] == [
        "Who I am", "Voice", "Custom Extra", "Hard rules",
    ]
    assert parsed["footer"] == "She/her."
    rendered = character.render_soul(parsed)
    again = character.parse_soul(rendered)
    assert again == parsed


def test_read_soul_orders_known_sections_first(home):
    soul = character.read_soul()
    titles = [s["title"] for s in soul["sections"]]
    assert titles.index("Voice") < titles.index("Custom Extra")
    assert titles.index("Hard rules") < titles.index("Custom Extra")  # known order, extras last
    assert soul["exists"] is True


def test_write_soul_replaces_sections(home):
    soul = character.write_soul(sections=[
        {"title": "Voice", "body": "Short and dry."},
        {"title": "Banned", "body": "No exclamation marks."},
    ])
    titles = [s["title"] for s in soul["sections"]]
    assert titles == ["Voice", "Banned"]
    assert "Short and dry." in (home / "SOUL.md").read_text(encoding="utf-8")
    assert "group friend" in soul["intro"]  # intro preserved when not sent


def test_write_soul_text_applies_presets(home):
    presets = character.personas()
    assert [p["id"] for p in presets] == ["current", "generic", "warm-friend", "dry-wit", "curious-mind"]
    soul = character.write_soul_text(next(p for p in presets if p["id"] == "warm-friend")["content"])
    assert "remembers" in soul["intro"].lower() or "friend" in soul["intro"].lower()
    with pytest.raises(Exception):
        character.write_soul_text("   ")


# ── Hard limits ──────────────────────────────────────────────────────────────────────────────────


def test_output_limits_read_and_write(home):
    limits = character.output_limits()
    assert limits["allowed_emoji"] == ["😭"]
    assert limits["max_lines"] == 4

    result = character.write_output_limits({"max_lines": 6, "allowed_emoji": ["😭", "💔"]})
    assert all(r["ok"] for r in result["results"].values())
    assert result["limits"]["max_lines"] == 6
    assert result["limits"]["allowed_emoji"] == ["😭", "💔"]
    assert "# keep me" in (home / "config.yaml").read_text(encoding="utf-8")


def test_output_limits_validation(home):
    bad = character.write_output_limits({"max_lines": 0, "nope": 1})
    assert not bad["results"]["max_lines"]["ok"]
    assert not bad["results"]["nope"]["ok"]


def test_sentence_breaks_can_be_disabled_from_dashboard_and_preview(home):
    result = character.write_output_limits({"style_filter": True, "sentence_breaks": False})
    assert all(row["ok"] for row in result["results"].values())
    assert result["limits"]["sentence_breaks"] is False
    assert character.preview_shaping("One. Two; hello ;)", "dm")["output"] == "One. Two; hello ;)"
    assert character.write_output_limits({"sentence_breaks": "false"})["results"]["sentence_breaks"]["ok"] is False


# ── Preview ──────────────────────────────────────────────────────────────────────────────────────


def test_preview_group_shaping_uses_config(home):
    report = character.preview_shaping("I am SO happy 😭 and 😡 about this!!!\n\n\n\n\n\nline", "group")
    assert report["surface"] == "group"
    assert report["changed"] is True
    assert "😡" not in report["output"]  # not in the allowlist
    assert "😭" in report["output"]
    assert len([l for l in report["output"].splitlines() if l.strip()]) <= 4
    assert any("emoji" in n for n in report["notes"])


def test_preview_dm_keeps_length(home):
    report = character.preview_shaping("one. two. three.", "dm")
    assert report["surface"] == "dm"
    # New characters preserve their chosen style; casual rhythm is an explicit opt-in.
    assert report["output"] == "one. two. three."


# ── Skins + skills ───────────────────────────────────────────────────────────────────────────────


def test_skins_list_and_set(home):
    (home / "skins").mkdir()
    (home / "skins" / "luna.yaml").write_text(
        "name: luna\ndescription: test\ncolors:\n  ui_accent: '#DF8DA5'\n", encoding="utf-8")
    skins = character.list_skins()
    names = [s["name"] for s in skins]
    assert names == ["default", "luna"]
    assert character.current_skin() == "default"
    result = character.set_skin("luna")
    assert result["ok"] and result["skin"] == "luna"
    assert any(s["active"] for s in character.list_skins() if s["name"] == "luna")


def test_write_skin_saves_colors_and_keeps_unknown_keys(home):
    (home / "skins").mkdir()
    (home / "skins" / "luna.yaml").write_text(
        "name: luna\nfonts:\n  body: Inter\ncolors:\n  ui_accent: '#DF8DA5'\n  banner_text: '#FBF0F8'\n",
        encoding="utf-8")
    result = character.write_skin("luna", {"ui_accent": "#112233"})
    assert result["ok"]
    saved = yaml.safe_load((home / "skins" / "luna.yaml").read_text(encoding="utf-8"))
    assert saved["colors"]["ui_accent"] == "#112233"
    assert saved["colors"]["banner_text"] == "#FBF0F8"  # untouched keys survive
    assert saved["fonts"] == {"body": "Inter"}              # non-color keys survive
    assert [s for s in character.list_skins() if s["name"] == "luna"][0]["colors"]["ui_accent"] == "#112233"


def test_write_skin_refuses_builtin_and_bad_values(home):
    (home / "skins").mkdir()
    assert character.write_skin("default", {"ui_accent": "#112233"})["ok"] is False
    assert character.write_skin("../evil", {"ui_accent": "#112233"})["ok"] is False
    assert character.write_skin("luna", {"ui_accent": "javascript:alert(1)"})["ok"] is False
    assert character.write_skin("luna", {})["ok"] is False


def test_write_skin_creates_a_new_file(home):
    result = character.write_skin("midnight", {"ui_accent": "#0B1020"}, "a dark skin")
    assert result["ok"]
    saved = yaml.safe_load((home / "skins" / "midnight.yaml").read_text(encoding="utf-8"))
    assert saved["name"] == "midnight" and saved["description"] == "a dark skin"
    character.set_skin("midnight")
    assert character.current_skin() == "midnight"


def test_skills_auto_load_toggle(home):
    (home / "skills" / "writing" / "humanizer").mkdir(parents=True)
    (home / "skills" / "writing" / "humanizer" / "SKILL.md").write_text("x", encoding="utf-8")
    skills = character.list_skills()
    assert any(s["name"] == "humanizer" and s["auto_loaded"] for s in skills)
    result = character.set_auto_load([])
    assert result["ok"] and result["auto_load"] == []
    assert "# keep me" in (home / "config.yaml").read_text(encoding="utf-8")


def test_character_bundle_shape(home):
    bundle = character.character_bundle()
    assert set(bundle) == {"soul", "output", "skins", "current_skin", "skills", "auto_load", "presets", "revision"}


def test_renaming_preserves_sections_and_updates_transport_identity(home):
    from luna_core.cascade import character_identity, build_questions
    before = character.read_soul()['sections']
    character.write_soul(title='Mira')
    assert character.read_soul()['sections'] == before
    assert character_identity()[0] == 'Mira'
    assert all('Luna' not in str(question) for question in build_questions())
    assert character.named_soul('# Companion\nOriginal voice.', 'Mira') == '# Mira\nOriginal voice.'
    before_bytes = (home / 'SOUL.md').read_text()
    with pytest.raises(ValueError):
        character.write_soul(title='Bad\nname')
    assert (home / 'SOUL.md').read_text() == before_bytes
