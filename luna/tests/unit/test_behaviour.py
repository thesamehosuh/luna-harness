"""Behaviour config (PRODUCT_PLAN P4): dry-run/budget/mention/reactions/jev writes stay
comment-preserving and validated."""

from __future__ import annotations

import pytest

from luna_cli import behaviour

CONFIG = """\
# top
luna:
  ambient:
    enabled: true
    dry_run: true
    room_register: "a quiet room."
    budget:
      message_cooldown_minutes: 0
    jev:
      timeout_seconds: 20
      route: [zen-free]
      providers:
        zen-free:
          base_url: https://opencode.ai/zen/v1
          model: jev-1.13-free
"""


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


def test_bundle_shape(home):
    bundle = behaviour.behaviour_bundle()
    assert bundle["dry_run"] is True
    assert bundle["room_register"] == "a quiet room."
    assert bundle["budget"]["message_cooldown_minutes"] == 0
    assert bundle["jev"]["route"] == ["zen-free"]
    assert "zen-free" in bundle["jev"]["providers"]


def test_write_dry_run_and_budget(home):
    result = behaviour.write_behaviour({
        "dry_run": False,
        "budget": {"message_cooldown_minutes": 30, "reaction_max_per_day": 4},
    })
    assert all(r["ok"] for r in result["results"].values())
    assert result["behaviour"]["dry_run"] is False
    assert result["behaviour"]["budget"]["message_cooldown_minutes"] == 30
    assert "# top" in (home / "config.yaml").read_text(encoding="utf-8")


def test_master_switch_settles_onboarding_and_retains_customizations(home):
    from luna_core.config_read import load_config
    behaviour.write_behaviour({"wake_prompts": {"message": "Keep it brief."}})
    for enabled in (True, False, True):
        result = behaviour.write_behaviour({"enabled": enabled})
        assert result["results"]["enabled"]["ok"]
        assert result["behaviour"]["enabled"] is enabled
        assert result["behaviour"]["wake_prompts"]["message"] == "Keep it brief."
        assert load_config()["luna"]["setup"]["jev"] == ("enabled" if enabled else "skipped")


def test_write_mentions_and_reactions(home):
    result = behaviour.write_behaviour({
        "mention_fallback": ["(?i)\\bluna\\b"],
        "reactions": {"allowed": ["😭", "👍"]},
    })
    assert all(r["ok"] for r in result["results"].values())
    assert result["behaviour"]["mention_fallback"] == ["(?i)\\bluna\\b"]
    assert result["behaviour"]["reactions"]["allowed"] == ["😭", "👍"]


def test_jev_route_validation(home):
    good = behaviour.write_behaviour({"jev": {
        "timeout_seconds": 30,
        "route": ["local", "zen-free"],
        "providers": {
            "local": {"base_url": "http://127.0.0.1:8700/v1", "model": "clm"},
            "zen-free": {"base_url": "https://opencode.ai/zen/v1", "model": "jev-1.13-free",
                         "api_key_env": "OPENCODE_ZEN_API_KEY"},
        },
    }})
    assert good["results"]["jev"]["ok"]
    assert good["behaviour"]["jev"]["route"] == ["local", "zen-free"]
    assert "zen-free" in good["behaviour"]["jev"]["providers"]

    # unknown route name and model-less provider are refused; config is untouched
    bad = behaviour.write_behaviour({"jev": {
        "route": ["ghost"],
        "providers": {"other": {"base_url": "http://x", "model": "m"}},
    }})
    assert not bad["results"]["jev"]["ok"]

    bad2 = behaviour.write_behaviour({"jev": {
        "route": ["ghost"], "providers": {"ghost": {"base_url": "http://x"}},
    }})
    assert not bad2["results"]["jev"]["ok"]


def test_unknown_and_bad_types_refused(home):
    result = behaviour.write_behaviour({"nope": 1, "poll_seconds": 0, "enabled": "yes"})
    assert not result["results"]["nope"]["ok"]
    assert not result["results"]["poll_seconds"]["ok"]
    assert not result["results"]["enabled"]["ok"]


def test_customizations_roundtrip_and_removal(home):
    rule = {"id": "interests", "name": "My interests", "instructions": "Is this about music?",
            "action": "message", "enabled": True, "threshold": 0.8}
    updates = {
        "decision": {"questions": {"message_would_fit": {"instructions": "Would a music tip help?"}}, "rules": [rule]},
        "reactions": {"allowed": ["💜"], "criteria": {"💜": "gentle support"}},
        "wake_prompts": {"message": "Offer one {contribution_type}.", "directed": "Answer the selected person."},
    }
    result = behaviour.write_behaviour(updates)
    assert all(row["ok"] for row in result["results"].values())
    for key, value in updates.items():
        assert result["behaviour"][key] == value
    assert result["behaviour"]["question_defaults"]
    assert result["behaviour"]["wake_prompt_defaults"]["message"]
    reset = behaviour.write_behaviour({"decision": {"questions": {}, "rules": []}, "reactions": {"allowed": [], "criteria": {}}, "wake_prompts": {}})
    assert reset["behaviour"]["decision"]["rules"] == []
    assert reset["behaviour"]["reactions"]["allowed"] == []
    assert reset["behaviour"]["wake_prompts"] == {}
    assert "# top" in (home / "config.yaml").read_text()


@pytest.mark.parametrize("updates", [
    {"decision": {"questions": {"private": {"instructions": ""}}}},
    {"decision": {"questions": {"made_up": {"instructions": "hello"}}}},
    {"decision": {"questions": {"private": {"criteria": {"true": "yes"}}}}},
    {"decision": {"rules": [{"id": "a", "name": "A", "instructions": "OK?", "threshold": float("nan") }]}},
    {"decision": {"rules": [{"id": "a", "name": "A", "instructions": "OK?", "action": "shell"}]}},
    {"wake_prompts": {"message": ""}},
    {"wake_prompts": {"other": "prompt"}},
    {"reactions": {"allowed": [123]}},
    {"reactions": {"allowed": [], "criteria": {"👍": []}}},
    {"jev": {"route": ["a"], "providers": {"a": {"model": "m", "instructions": []}}}},
])
def test_bad_customization_keeps_entire_draft_unchanged(home, updates):
    before = (home / "config.yaml").read_text()
    result = behaviour.write_behaviour({"room_register": "should not write", **updates})
    assert not any(row["ok"] for row in result["results"].values())
    assert (home / "config.yaml").read_text() == before


def test_conversation_save_reads_staged_values_and_preserves_other_fields(home):
    result = behaviour.write_behaviour({"conversation": {"max_turns_per_burst": 2}, "room_register": "a busy room"})
    assert all(row["ok"] for row in result["results"].values())
    assert result["behaviour"]["conversation"]["max_turns_per_burst"] == 2
    assert result["behaviour"]["conversation"]["max_pending"] == 16
    assert result["behaviour"]["room_register"] == "a busy room"
    assert behaviour.behaviour_bundle()["conversation"]["max_turns_per_burst"] == 2
    before = (home / "config.yaml").read_text()
    bad = behaviour.write_behaviour({"conversation": {"max_pending": 0}, "dry_run": False})
    assert not any(row["ok"] for row in bad["results"].values())
    assert (home / "config.yaml").read_text() == before
