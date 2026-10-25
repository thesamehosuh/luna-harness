"""Recall budget enforcement — the 58,335-char prefetch regression and ranking."""

from __future__ import annotations

from luna_core.budget import (
    TRUNCATION_MARKER,
    approx_tokens,
    enforce_budget,
    rank_sections,
)


def test_enforce_budget_passes_short_text_through():
    res = enforce_budget("hello", max_chars=100)
    assert res.text == "hello"
    assert res.truncated is False


def test_enforce_budget_clamps_the_58335_char_prefetch():
    prefetch = "peer fact line\n" * 4000  # ~60k chars
    assert len(prefetch) > 58335
    res = enforce_budget(prefetch, max_chars=2000)
    assert res.chars <= 2000
    assert res.truncated is True
    assert res.text.endswith(TRUNCATION_MARKER)


def test_enforce_budget_cuts_at_a_boundary_not_mid_word():
    text = "word " * 1000
    res = enforce_budget(text, max_chars=100)
    assert res.chars <= 100
    assert not res.text.replace(TRUNCATION_MARKER, "").rstrip().endswith("wor")


def test_rank_sections_prefers_higher_scores():
    sections = [
        (0.1, "low relevance block"),
        (0.9, "high relevance block"),
        (0.5, "medium relevance block"),
    ]
    res = rank_sections(sections, max_chars=45)
    assert "high relevance block" in res.text
    assert "low relevance block" not in res.text
    assert res.dropped >= 1


def test_rank_sections_includes_all_when_they_fit():
    sections = [(0.9, "a"), (0.5, "b"), (0.1, "c")]
    res = rank_sections(sections, max_chars=1000)
    assert res.text == "a\n\nb\n\nc"
    assert res.truncated is False


def test_rank_sections_hard_truncates_when_none_fit():
    sections = [(0.9, "x" * 500)]
    res = rank_sections(sections, max_chars=50)
    assert res.chars <= 50


def test_approx_tokens():
    assert approx_tokens("abcd") == 1
    assert approx_tokens("a" * 400) == 100
