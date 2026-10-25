"""Per-surface shaping: hard group limits, TTS expansion, English-only guard."""

from __future__ import annotations

from luna_core import text as text_mod
from luna_core.text import (
    ENGLISH_ONLY_FALLBACK,
    MAX_GROUP_LINES,
    clamp_lines,
    contains_farsi,
    expand_abbreviations,
    guard_english,
    keep_only_allowed_emoji,
    shape_dm_reply,
    shape_for_surface,
    shape_group_reply,
    strip_emoji,
    strip_markdown,
)


def _set_policy(tmp_path, monkeypatch, *, strip_emoji=False, allowed=None, emoji_filter=None):
    """Point the emoji policy at a throwaway config and drop the mtime cache."""
    cfg = "luna:\n  output:\n"
    if emoji_filter is not None:
        cfg += "    emoji_filter: %s\n" % ("true" if emoji_filter else "false")
    cfg += "    strip_emoji: %s\n" % ("true" if strip_emoji else "false")
    if allowed is not None:
        cfg += "    allowed_emoji: [%s]\n" % ", ".join('"%s"' % a for a in allowed)
    (tmp_path / "config.yaml").write_text(cfg, encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    text_mod._EMOJI_POLICY_CACHE = None


import pytest


@pytest.fixture(autouse=True)
def _hermetic_emoji_policy(tmp_path, monkeypatch):
    """Never read the operator's live config: default policy = empty allowlist (no emoji)."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("luna: {output: {style_filter: true}}\n")
    text_mod._EMOJI_POLICY_CACHE = None
    yield
    text_mod._EMOJI_POLICY_CACHE = None


def test_style_filter_off_preserves_voice_and_dm_code_formatting(tmp_path):
    (tmp_path / "config.yaml").write_text("luna: {output: {style_filter: false}}\n")
    source = "Hello. A second sentence.\n\n```python\n    example()\n```"
    assert shape_dm_reply(source) == source
    assert shape_group_reply("Hello. A second sentence.") == "Hello. A second sentence."


@pytest.mark.parametrize("face", [":)", ":-)", ";)", ";-P", ":D", ":(", ":/", ":'(", "^_^", "T_T", "xD"])
def test_chat_style_preserves_emoticons_and_their_spacing(face):
    assert shape_dm_reply(f"hello {face}") == f"hello {face}"
    assert shape_dm_reply(f"One. {face} Two.") == f"One {face}\nTwo"
    assert shape_dm_reply(f"Really? {face} Next.") == f"Really? {face}\nNext"


def test_rhythm_protects_urls_semicolons_quotes_and_code():
    out = shape_dm_reply('look https://example.test/a;b. Next; wink ;) and `a;b` or "a; b".')
    assert "https://example.test/a;b." in out
    assert "wink ;)" in out and "`a;b`" in out and '"a; b"' in out


def test_sentence_break_switch_is_separate_from_casual_rewrites_and_keeps_hard_group_limits(tmp_path):
    (tmp_path / "config.yaml").write_text("luna: {output: {style_filter: true, sentence_breaks: false, max_lines: 2}}\n")
    source = "One. Two; Three. hello ;)"
    assert shape_dm_reply(source) == source
    assert shape_dm_reply("Great question! " + source) == source
    group = shape_group_reply(source + "\nsecond\nthird")
    assert source in group and len(group.splitlines()) == 2


def test_keep_only_allowed_emoji_filters_everything_else():
    out = keep_only_allowed_emoji("dead plans 💔 🔥 😭 😀", ("💔", "😭"))
    assert "💔" in out and "😭" in out
    assert "🔥" not in out and "😀" not in out


def test_keep_only_allowed_emoji_empty_allowlist_strips_all():
    assert keep_only_allowed_emoji("nope 💔 😭", ()) == "nope  "


def test_emoji_policy_reads_config_allowlist(tmp_path, monkeypatch):
    _set_policy(tmp_path, monkeypatch, allowed=["💔"])
    strip_all, allowed = text_mod.emoji_policy()
    assert strip_all is False and allowed == ("💔",)


def test_emoji_policy_missing_config_means_no_emoji(tmp_path, monkeypatch):
    """No code defaults: an absent allowlist is an empty allowlist."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    text_mod._EMOJI_POLICY_CACHE = None
    assert text_mod.emoji_policy() == (False, ())


def test_group_shape_keeps_only_allowlisted_emoji(tmp_path, monkeypatch):
    _set_policy(tmp_path, monkeypatch, allowed=["💔", "😭"])
    out = shape_group_reply("cooked 💔 really 😭 and 🔥 too")
    assert "💔" in out and "😭" in out and "🔥" not in out


def test_group_shape_strip_emoji_true_removes_all(tmp_path, monkeypatch):
    _set_policy(tmp_path, monkeypatch, strip_emoji=True, allowed=["💔", "😭"])
    out = shape_group_reply("cooked 💔 really 😭")
    assert "💔" not in out and "😭" not in out


def test_strip_emoji_removes_pictographs_but_keeps_punctuation():
    assert strip_emoji("hey 🔥 there 👀!") == "hey  there !"
    assert strip_emoji("plain, text. (fine)") == "plain, text. (fine)"


def test_strip_markdown_removes_headers_and_emphasis():
    src = "## Heading\n**bold** and _italic_ and `code`\n- bullet"
    out = strip_markdown(src)
    assert "Heading" in out and "#" not in out
    assert "bold" in out and "*" not in out
    assert "`" not in out
    assert "- bullet" not in out and "bullet" in out


def test_clamp_lines_keeps_at_most_four():
    src = "\n".join(f"line {i}" for i in range(10))
    out = clamp_lines(src)
    assert out.count("\n") == MAX_GROUP_LINES - 1
    assert out.startswith("line 0")
    assert "line 4" not in out


def test_shape_group_reply_applies_all_limits():
    src = "# **Hi** 🔥\nline two\nline three\nline four\nline five"
    out = shape_group_reply(src)
    assert "#" not in out and "*" not in out and "🔥" not in out
    assert len(out.splitlines()) <= MAX_GROUP_LINES
    # The cap is met by repacking, never by silent loss: overflow merges onto the last line.
    assert "line five" in out


def test_expand_abbreviations_for_tts():
    out = expand_abbreviations("cats, dogs, etc. and e.g. birds w/ wings")
    assert "etc." not in out and "and so on" in out
    assert "e.g." not in out and "for example" in out
    assert " w/ " not in out and " with " in out


def test_shape_for_surface_group_vs_dm():
    src = "**one** 🔥\ntwo\nthree\nfour\nfive"
    group = shape_for_surface(src, "group")
    dm = shape_for_surface(src, "dm")
    assert len(group.splitlines()) <= MAX_GROUP_LINES
    assert "*" not in group and "🔥" not in group
    # DM keeps the emoji and is not line-clamped.
    assert "🔥" in dm
    assert len(dm.splitlines()) == 5


def test_tts_flag_expands_only_when_requested():
    src = "bring snacks etc."
    # Non-TTS: chat rhythm drops the sentence-final dot ("etc." -> "etc").
    assert shape_for_surface(src, "dm", for_tts=False).endswith("etc")
    assert "and so on" in shape_for_surface(src, "dm", for_tts=True)


def test_contains_farsi_and_guard():
    assert contains_farsi("سلام")
    assert not contains_farsi("hello")
    assert guard_english("hello") == "hello"
    assert guard_english("سلام", fallback="") == ""
    assert guard_english("سلام") is None


def test_group_shape_strips_farsi_when_language_policy_is_english(monkeypatch):
    monkeypatch.setattr("luna_core.text.output_config", lambda: {"language": "english"})
    """English only on the group surface — never Farsi, even if asked in Farsi."""
    out = shape_group_reply("sure, here you go سلام دوست من")
    assert "سلام" not in out
    assert "sure, here you go" in out
    # An entirely non-English draft becomes the fixed English fallback.
    assert shape_group_reply("سلام خوبی") == ENGLISH_ONLY_FALLBACK


def test_group_shape_redacts_personal_details():
    out = shape_group_reply("call me at 0912 345 6789 or mail a.b@mail.com")
    assert "0912 345 6789" not in out
    assert "a.b@mail.com" not in out
    assert "[redacted]" in out


def test_language_policy_covers_non_latin_scripts_without_affecting_auto(monkeypatch):
    for sample in ("こんにちは", "你好", "Привет", "سلام"):
        monkeypatch.setattr("luna_core.text.output_config", lambda: {"language": "auto"})
        assert shape_group_reply(sample) == sample
        monkeypatch.setattr("luna_core.text.output_config", lambda: {"language": "english"})
        assert shape_group_reply(sample) == ENGLISH_ONLY_FALLBACK


def test_group_shape_keeps_ordinary_numbers():
    """Dates, counts, and small numbers are not personal details and must survive."""
    out = shape_group_reply("we were 29 members on 2026-09-26, cost was 58,335")
    assert "29" in out and "2026-09-26" in out and "58,335" in out


def test_dm_surface_is_unrestricted():
    """DM output is not line-clamped, not redacted — only the group surface is shaped."""
    dm = shape_dm_reply("call 0912 345 6789\n\n\n\n\nfive\nsix")
    assert "0912 345 6789" in dm


def test_chat_rhythm_replaces_separators_with_line_breaks():
    """The "." / ";" is REPLACED by the break — it must not ride along to the next line."""
    out = shape_dm_reply("I disagree. It's a bad idea. Also; the timing is wrong — go tomorrow.")
    assert out == "I disagree\nIt's a bad idea\nAlso\nthe timing is wrong\ngo tomorrow"


def test_chat_rhythm_keeps_exceptions():
    out = shape_dm_reply("wait... Really. Are you coming? I can wait!")
    assert out == "wait...\nReally\nAre you coming?\nI can wait!"


def test_chat_rhythm_keeps_commas():
    """Commas are clause rhythm, not line breaks: splitting on them shreds lists."""
    out = shape_dm_reply("got bread, milk, and eggs on 2026-09-26")
    assert out == "got bread, milk, and eggs on 2026-09-26"


def test_chat_rhythm_respects_abbreviations():
    out = shape_dm_reply("pick a pet, e.g. a cat. Then decide.")
    assert out == "pick a pet, e.g. a cat\nThen decide"
    assert "fig. 3" in shape_dm_reply("see fig. 3 for details")


def test_chat_rhythm_never_splits_quotes_or_code():
    out = shape_dm_reply('he said "wait. really?" and left. Then called `foo.bar` back.')
    assert '"wait. really?"' in out
    assert "`foo.bar`" in out
    assert out.endswith("called `foo.bar` back")


def test_chat_rhythm_repacks_to_the_line_cap_without_dropping_content():
    src = "One is here. Two is here. Three is here. Four is here. Five is here."
    out = shape_group_reply(src)
    assert len(out.splitlines()) <= MAX_GROUP_LINES
    for word in ("One", "Two", "Three", "Four", "Five"):
        assert word in out  # repack merges lines; the clamp must never be the one dropping


def test_dm_rhythm_is_uncapped():
    out = shape_dm_reply("One. Two. Three. Four. Five. Six.")
    assert len(out.splitlines()) == 6


def test_media_placeholder_path_is_stripped_from_observed_text():
    from luna_core.text import strip_media_placeholders

    only = "[video 'troll-face.mp4' saved at: /home/user/.luna/cache/videos/video_b099.mp4]"
    assert strip_media_placeholders(only) == ""
    # A caption survives; the placeholder (and its path) does not.
    caption = "Why so specific\n\n[image 'file_330.jpg' saved at: /home/user/.luna/cache/images/img_559.jpg]"
    assert strip_media_placeholders(caption) == "Why so specific"
    # A bare cache path outside a bracket is dropped too.
    assert strip_media_placeholders("look /home/user/.luna/cache/videos/x.mp4 here") == "look here"
    # No path, no "luna" → untouched.
    assert strip_media_placeholders("just talking about luna") == "just talking about luna"


def test_emoji_filter_false_keeps_every_emoji(tmp_path, monkeypatch):
    from luna_core.text import shape_group_reply

    _set_policy(tmp_path, monkeypatch, emoji_filter=False, allowed=["\U0001F494"])
    assert text_mod.emoji_policy() == (False, None)  # None = passthrough
    out = shape_group_reply("dead \U0001F525 and \U0001F600 and \U0001F494")
    for emo in ("\U0001F525", "\U0001F600", "\U0001F494"):
        assert emo in out


def test_emoji_filter_true_still_uses_the_allowlist(tmp_path, monkeypatch):
    from luna_core.text import shape_group_reply

    _set_policy(tmp_path, monkeypatch, emoji_filter=True, allowed=["\U0001F494"])
    assert text_mod.emoji_policy() == (False, ("\U0001F494",))
    out = shape_group_reply("dead \U0001F494 \U0001F525")
    assert "\U0001F494" in out and "\U0001F525" not in out


def test_chat_rhythm_breaks_before_a_number():
    """A sentence before a number breaks ("Done. 11am"); only named abbreviations are protected."""
    from luna_core.text import shape_dm_reply

    assert shape_dm_reply("Done. 11am is sandwich time") == "Done\n11am is sandwich time"
    assert shape_dm_reply("see fig. 3 for details") == "see fig. 3 for details"
    assert shape_dm_reply("no. 5 is the one") == "no. 5 is the one"


def test_redaction_is_linear_on_long_digit_runs():
    """The P6 DoS fix: ``transform_llm_output`` is timeout-bounded, and a hook that times out is
    discarded — which ships the *raw* reply. A long digit run is reachable in model output, so the
    quadratic regex became a denial-of-service on the privacy control."""
    import time

    from luna_core.text import redact_personal_details

    # Behaviour is preserved across the slicing boundary: a number straddling it still redacts.
    padded = "x" * 5000 + " call 10000000100 now"
    assert "10000000100" not in redact_personal_details(padded)
    assert "[redacted]" in redact_personal_details(padded)

    started = time.perf_counter()
    redact_personal_details("9" * 60_000)
    elapsed = time.perf_counter() - started
    # Quadratic behaviour measured ~13s for this input; a generous ceiling still fails loudly
    # without being flaky on a loaded machine.
    assert elapsed < 5.0, f"redaction took {elapsed:.1f}s — the slicing regressed"
