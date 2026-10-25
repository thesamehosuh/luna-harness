"""Luna tip corpus keeps product copy accurate and resolves engine homes at runtime."""

from pathlib import Path

from hermes_cli import tips


def test_random_tip_expands_home_from_active_runtime(monkeypatch):
    selected = next(tip for tip in tips.TIPS if "{HERMES_HOME}" in tip)
    monkeypatch.setattr(tips.random, "choice", lambda _items: selected)
    monkeypatch.setattr("hermes_constants.get_hermes_home", lambda: Path("/srv/luna/profiles/dev"))

    rendered = tips.get_random_tip()

    assert "/srv/luna/profiles/dev" in rendered
    assert "{HERMES_HOME}" not in rendered


def test_tip_corpus_avoids_retired_commands_and_terminal_config_edits():
    corpus = "\n".join(tips.TIPS).lower()

    assert "luna tune" not in corpus
    assert "luna peers" not in corpus
    assert "hermes tune" not in corpus
    assert "hermes peers" not in corpus
    assert "edit config.yaml" not in corpus
    assert "set display." not in corpus


def test_engine_compatibility_identifiers_remain_documented():
    corpus = "\n".join(tips.TIPS)

    assert ".hermes.md" in corpus
    assert ".hermes/" in corpus
    assert "HERMES_HOME" in corpus
    assert "LUNA_HOME" in corpus
    assert "hermes_tools" in corpus
