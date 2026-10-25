"""Tests for the curated Luna tip corpus and its runtime rendering."""

from hermes_cli import tips
from hermes_cli.tips import TIPS, get_random_tip


class TestTipsCorpus:
    """Validate the tip corpus itself."""

    def test_all_tips_are_strings(self):
        for i, tip in enumerate(TIPS):
            assert isinstance(tip, str), f"Tip {i} is not a string: {type(tip)}"
            assert tip.strip(), f"Tip {i} is empty"
        assert len(TIPS) == len(set(TIPS)), "The curated corpus should not repeat tips"

    def test_corpus_is_curated_and_avoids_retired_cli_advice(self):
        corpus = "\n".join(TIPS).lower()
        assert "luna tune" not in corpus
        assert "luna peers" not in corpus
        assert "hermes tune" not in corpus
        assert "hermes peers" not in corpus
        assert "edit config.yaml" not in corpus
        assert "set display." not in corpus


class TestGetRandomTip:
    """Validate the get_random_tip() function."""

    def test_returns_string(self):
        tip = get_random_tip()
        assert isinstance(tip, str)
        assert len(tip) > 0

    def test_returns_tip_from_corpus(self):
        tip = get_random_tip()
        from hermes_constants import get_hermes_home

        rendered_corpus = {
            entry.replace("{HERMES_HOME}", str(get_hermes_home())) for entry in TIPS
        }
        assert tip in rendered_corpus

    def test_runtime_rendering_never_leaks_placeholders(self, monkeypatch):
        for entry in TIPS:
            monkeypatch.setattr(tips.random, "choice", lambda _items, item=entry: item)
            assert "{HERMES_HOME}" not in get_random_tip()

    def test_randomness(self):
        """Multiple calls should eventually return different tips."""
        seen = set()
        for _ in range(50):
            seen.add(get_random_tip())
        # The curated corpus should still offer enough variety across a short run.
        assert len(seen) >= 10, f"Only got {len(seen)} unique tips in 50 draws"


class TestTipIntegrationInCLI:
    """Test that the tip display code in cli.py works correctly."""


    def test_tip_display_format(self):
        """Verify the Rich markup format doesn't break."""
        tip = get_random_tip()
        color = "#B8860B"
        markup = f"[dim {color}]✦ Tip: {tip}[/]"
        # Should not contain nested/broken Rich tags
        assert markup.count("[/]") == 1
        assert "[dim #B8860B]" in markup
