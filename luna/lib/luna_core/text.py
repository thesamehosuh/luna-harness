"""Per-surface output shaping — the hard limits enforced in code, not just in the prompt.

The persona (SOUL.md) asks for brevity and a small emoji allowlist; this module *enforces* it so a
drifting model cannot violate the group contract. Group replies are clamped to ``MAX_GROUP_LINES``
lines with emoji filtered to the ``luna.output.allowed_emoji`` allowlist (or stripped entirely when
``luna.output.strip_emoji`` is true), markdown headers stripped, and personal-detail patterns
(emails, phone/ID-like digit runs) redacted. Language follows the conversation by default; an
explicit English policy filters non-Latin letters. This is a script guard, not a language classifier.

The mechanical subset of the humanizer rules (vendored at luna/skills/creative/humanizer) is
enforced here on **every** reply, not just the room: chatbot residue, staged openers, and dash
churn are stripped deterministically so the model never has to "call the skill" for normal talking.
Semantic tells (not-X-but-Y, one-line closers, inflated significance) stay with SOUL.md — code
cannot rewrite prose safely. Quoted spans and code spans are protected: quoting AI slop must not
be mangled. TTS output gets abbreviations expanded.
"""

from __future__ import annotations

from luna_core.runtime import home as runtime_home, getenv

import re
import unicodedata
from typing import Optional

MAX_GROUP_LINES = 4
# Deterministic fallback when a draft is entirely non-English (the hook cannot regenerate).
ENGLISH_ONLY_FALLBACK = "let's keep it in english"

# Adapter attachment placeholders, e.g. "[image 'x.jpg' saved at: /home/…/.luna/cache/images/…]".
_MEDIA_PLACEHOLDER_RE = re.compile(r"\[[^\[\]]*\bsaved at:\s*[^\[\]]*\]", re.IGNORECASE)
# A bare media-cache path that escaped its bracket (defensive).
_LUNA_CACHE_PATH_RE = re.compile(r"\S*\.luna[\\/]cache[\\/]\S*", re.IGNORECASE)


def strip_media_placeholders(text: str) -> str:
    """Remove attachment placeholders (and their host paths) from observed message text.

    The gateway renders an attachment as ``[image 'x.jpg' saved at: /home/…/.luna/cache/…]``.
    Indexed verbatim, the absolute path makes the message look like a mention of Luna — the path
    contains ``.luna`` — so jev and the regex fallback wake her on a meme. A caption is preserved;
    only the placeholder and any bare ``.luna/cache`` path are dropped, leaving "" for media-only
    messages (which ``is_substantive`` then rejects).
    """
    if not text:
        return text
    cleaned = _MEDIA_PLACEHOLDER_RE.sub(" ", text)
    cleaned = _LUNA_CACHE_PATH_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return "\n".join(part.strip() for part in cleaned.splitlines()).strip()

# Emoji / pictograph ranges (kept deliberately tight so normal punctuation survives).
_EMOJI_RANGES = (
    "\U0001F300-\U0001FAFF"  # pictographs, supplemental, extended-A
    "\U0001F1E6-\U0001F1FF"  # regional indicators (flags)
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U00002B00-\U00002BFF"  # misc symbols and arrows
    "\U0001F000-\U0001F0FF"  # mahjong / dominoes / cards
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner
    "\U000020E3"             # combining enclosing keycap
)
_EMOJI_RE = re.compile(f"[{_EMOJI_RANGES}]+")

# Arabic / Persian script ranges — used by the English-only guard.
_FARSI_RANGES = "\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff"
_FARSI_RE = re.compile(f"[{_FARSI_RANGES}]")

_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_INLINE_MD_RE = re.compile(r"(\*\*|__|~~|`{1,3})")
_LEADING_BULLET_RE = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)

# Personal details (privacy rule: never another member's). Deterministic subset only: email
# addresses and phone/ID-like digit runs (10+ digits, or international +NNNN…). Ordinary small
# numbers ("we were 29", "2026-09-26", "58,335") survive — dates and counts are not details.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\d)\+?\d(?:[\s().-]*\d){9,}(?!\d)")
# Slice size for redact_personal_details; see its docstring for why the split is needed.
_REDACT_SLICE_CHARS = 4096

# TTS: expanded abbreviations (never leave raw "e.g."/"etc." in spoken output).
_TTS_ABBREVIATIONS = {
    "e.g.": "for example",
    "i.e.": "that is",
    "etc.": "and so on",
    "vs.": "versus",
    "w/": "with",
    "w/o": "without",
    "&": "and",
    "approx.": "approximately",
    "min.": "minutes",
    "max.": "maximum",
    "no.": "number",
}
_TTS_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(_TTS_ABBREVIATIONS, key=len, reverse=True)),
    re.IGNORECASE,
)


def strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text or "")


# Emoji policy (config: ``luna.output``). The allowlist is config-only — no code defaults.
def keep_only_allowed_emoji(text: str, allowed) -> str:
    """Remove every emoji except the allowlisted ones (exact matches survive)."""
    out = text or ""
    tokens = []
    for i, emo in enumerate(allowed or ()):
        if not emo:
            continue
        token = f"\x00EMOJI{i}\x00"
        out = out.replace(emo, token)
        tokens.append((token, emo))
    out = strip_emoji(out)
    for token, emo in tokens:
        out = out.replace(token, emo)
    return out


_OUTPUT_CACHE: Optional[dict] = None
_OUTPUT_MTIME = -1.0
_OUTPUT_HOME = ""


def output_config() -> dict:
    """``luna.output`` from $HERMES_HOME/config.yaml (mtime-cached). Shaping knobs live here:
    ``emoji_filter`` / ``strip_emoji`` / ``allowed_emoji`` and the hard length limit ``max_lines``.
    """
    global _OUTPUT_CACHE, _OUTPUT_MTIME, _OUTPUT_HOME
    import os
    from pathlib import Path

    home = runtime_home()
    path = home / "config.yaml"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0
    home_key = str(home)
    if _OUTPUT_CACHE is None or mtime != _OUTPUT_MTIME or home_key != _OUTPUT_HOME:
        out: dict = {}
        try:
            import yaml

            from luna_core.config_read import with_defaults
            data = with_defaults(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
            raw = (data.get("luna") or {}).get("output") or {}
            if isinstance(raw, dict):
                out = raw
        except Exception:
            out = {}
        _OUTPUT_CACHE = out
        _OUTPUT_MTIME = mtime
        _OUTPUT_HOME = home_key
    return _OUTPUT_CACHE


def group_max_lines() -> int:
    """Hard line cap for group replies: ``luna.output.max_lines``, default :data:`MAX_GROUP_LINES`."""
    try:
        value = int(output_config().get("max_lines"))
    except (TypeError, ValueError):
        return MAX_GROUP_LINES
    return value if value > 0 else MAX_GROUP_LINES


def emoji_policy():
    """``(strip_all, allowed)`` from ``luna.output`` in $HERMES_HOME/config.yaml (mtime-cached).

    ``strip_emoji: true`` removes every emoji. ``emoji_filter: false`` turns emoji shaping off
    entirely — ``allowed`` comes back as ``None`` and no emoji is touched. Otherwise only the
    ``allowed_emoji`` allowlist survives. The allowlist is config-only: a missing key is an empty
    allowlist (no emoji), never a hardcoded set.
    """
    out = output_config()
    strip_all = bool(out.get("strip_emoji", False))
    allowed: Optional[tuple] = ()
    filter_emoji = out.get("emoji_filter", True)
    if isinstance(filter_emoji, str):
        filter_emoji = filter_emoji.strip().lower() not in {"false", "0", "no", "off"}
    if not filter_emoji:
        allowed = None  # explicit passthrough: every emoji survives
    else:
        raw = out.get("allowed_emoji")
        if isinstance(raw, list):
            allowed = tuple(str(a) for a in raw)
        else:
            allowed = ()
    return strip_all, allowed


def strip_markdown(text: str) -> str:
    """Remove headers, inline emphasis markers, and leading bullets. Keeps code blocks' contents."""
    text = _HEADER_RE.sub("", text)
    text = _INLINE_MD_RE.sub("", text)
    text = _LEADING_BULLET_RE.sub("", text)
    return text


def clamp_lines(text: str, max_lines: int = MAX_GROUP_LINES) -> str:
    """Keep at most ``max_lines`` non-empty lines."""
    lines = [ln.rstrip() for ln in (text or "").strip().splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    return "\n".join(lines[:max_lines])


def normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def redact_personal_details(text: str) -> str:
    """Mask emails and phone/ID-like digit runs (the privacy rule's deterministic subset).

    Code cannot tell *whose* detail a phone number is, so it masks all of them on the group
    surface: a leaked detail is unrecoverable, a masked one is recoverable by asking.

    ``_PHONE_RE`` is quadratic on a long *contiguous* digit run (measured: 13s for 60k digits —
    the ``(?:[\\s().-]*\\d){9,}`` repeat backtracks across every start offset), and this runs
    inside ``transform_llm_output``, which is timeout-bounded: a hook that times out is discarded,
    which would ship the *raw* reply. Model output is attacker-influenced (see the room-block
    injection surface), so a long digit run is reachable. Work is therefore done in
    whitespace-aligned slices, which bounds the cost while leaving every realistic phone number
    (tens of characters, at most a few interior spaces) wholly inside one slice.
    """
    text = text or ""
    if len(text) <= _REDACT_SLICE_CHARS:
        return _PHONE_RE.sub("[redacted]", _EMAIL_RE.sub("[redacted]", text))
    parts: list[str] = []
    start = 0
    limit = len(text)
    while start < limit:
        end = min(start + _REDACT_SLICE_CHARS, limit)
        if end < limit:
            # Prefer a whitespace boundary so a slice edge cannot land inside a short number.
            space = text.rfind(" ", start + _REDACT_SLICE_CHARS // 2, end)
            if space > start:
                end = space + 1
        parts.append(_PHONE_RE.sub("[redacted]", _EMAIL_RE.sub("[redacted]", text[start:end])))
        start = end
    return "".join(parts)


# --- humanizer (mechanical subset) ----------------------------------------- #
# Faces are punctuation to a regex, but content to a person. Protect them before
# whitespace cleanup ("hello :)" used to become "hello:)"), and before splitting
# semicolons (which destroyed winks). URLs also contain non-sentence separators.
_EMOTICON_PATTERN = r"(?:[<>]?[=:;8][\-^oO']?[)\](\[dDpP/\\|3{}oOsS]+|[xX][dD]+|\^[_ .-]?\^|[Tt][_.-][Tt]|[Oo][_.-][Oo]|-_-)(?!\w)"
_EMOTICON_RE = re.compile(_EMOTICON_PATTERN)
_PROTECT_RE = re.compile(r"(```.*?```|`[^`\n]*`|\"[^\"]*\"|https?://[^\s<>]+|" + _EMOTICON_PATTERN + r")", re.DOTALL)

# Chatbot wrappers and pure-emphasis closers: removable without changing any claim.
_RESIDUE_RE = re.compile(
    r"(great question\s*!|that'?s a great question\s*!|"
    r"i hope this helps|i hope that helps|"
    r"let me know if (you need|you have|there is|there's)[^.\n]*|"
    r"feel free to ask[^.\n]*|i('?d| would) be happy to help|happy to help with that|"
    r"i appreciate you sharing (that|this)|thanks for sharing (that|this)|"
    r"you'?re absolutely right|"
    r"as an ai( language model)?|i'?m an ai|"
    r"that is the real win\s*\.?|that'?s the real win\s*\.?|read that again\s*\.?|"
    r"let that sink in\s*\.?|in conclusion\s*[,;:]?|in summary\s*[,;:]?)",
    re.IGNORECASE,
)

# Staged openers: discourse markers that announce a point instead of making it. Only the pure
# wrappers — "I'm not saying X" carries a negation and is never stripped.
_OPENER_RE = re.compile(
    r"(?im)^\s*(honestly\s*[,:?!]|let'?s be honest\s*[,;:]|here'?s the thing\s*[,;:]|"
    r"the thing is\s*[,;:]|real talk\s*[,;:]|to be clear\s*[,;:]|don'?t get me wrong\s*[,;:]|"
    r"without further ado\s*[,;:]|let'?s dive in\s*[.!]?)\s*"
)

# Line-break rhythm (chat typing): sentence separators are REPLACED by the break — the "." or ";"
# must never ride along to the next line. Exceptions kept on purpose: ellipses ("wait..."),
# "?" / "!" (they carry the question or exclamation), dotted abbreviations (e.g., etc.),
# number continuations ("fig. 3"), and quoted/code spans (protected above). Commas stay commas.
# Single hyphens survive (hyphenated words, date ranges).
_DASH_RE = re.compile(r"\s*[—–]\s*|\s+--\s+")
_SEMI_RE = re.compile(r"[ \t]*;[ \t]*")
# Whitespace around a line break: the space that follows a separator (or precedes a model's own
# newline) must never reach the next line — a break eats the padding on both sides.
_LINE_EDGE_RE = re.compile(r"[ \t]*\n[ \t]*")
# Ellipsis runs keep their dots and just break.
_ELLIPSIS_BREAK_RE = re.compile(r"(\.{2,}[?!]?)\s+")
# "?" / "!" keep the marks and break.
_QUEST_BREAK_RE = re.compile(r"([?!]+)\s+")
# A single "." boundary: the dot is DROPPED and the break takes its place. Skipped after dotted
# abbreviations (guards anchor at the dot) and inside dot runs (the rules above own those). A break
# before a NUMBER is taken — "Done. 11am" breaks — and only named numbered abbreviations
# ("fig. 3", "no. 5") are protected, via `_NUMBERED_ABBREV_RE` placeholders around this rule.
_DOT_BREAK_RE = re.compile(
    r"(?<![eE]\.[gG])(?<![iI]\.[eE])(?<!\b[eE]tc)(?<!\b[vV]s)"
    r"(?<!\b[mM]r)(?<!\b[mM]rs)(?<!\b[mM]s)(?<!\b[dD]r)(?<!\b[pP]rof)"
    r"(?<!\.)\.(?!\.)\s+"
)
# Numbered abbreviations keep their dot so "fig. 3" doesn't become "fig\n3". Placeholder-protected
# rather than a blanket digit guard, which would also block an ordinary sentence before a number.
_NUMBERED_ABBREV_RE = re.compile(
    r"\b(?:fig|figs|no|nos|vol|vols|ch|chs|sec|secs|eq|eqs|art|arts|ref|refs|para|paras|approx)"
    r"\.",
    re.IGNORECASE,
)
_NUMBERED_ABBREV_TOKEN = "\x00DOT\x00"
# Message-final separators are dropped ("Two." → "Two", "wait;" → "wait"); ellipses and ?/! stay.
def _drop_trailing_separator(text: str) -> str:
    out = text.rstrip()
    if out.endswith(";"):
        out = out[:-1].rstrip()
    elif out.endswith(".") and not out.endswith(".."):
        out = out[:-1].rstrip()
    return out


def _strip_de_ai_segment(text: str) -> str:
    text = _OPENER_RE.sub("", text)
    text = _RESIDUE_RE.sub("", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)   # "word ," → "word,"
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def de_ai_text(text: str) -> str:
    """Strip the mechanical AI tells from Luna's own prose on every reply.

    Quoted spans and code spans are left alone. Semantic tells (not-X-but-Y, one-line closers
    beyond the fixed list, inflated significance) ride the skill, which is auto-loaded into the
    system prompt (``skills.auto_load``) — code must not rewrite meaning.
    """
    text = text or ""
    parts = _PROTECT_RE.split(text)
    for i in range(0, len(parts), 2):
        parts[i] = _strip_de_ai_segment(parts[i])
    return "".join(parts)


def _pack_lines(text: str, max_lines: int) -> str:
    """Merge tail lines until the text fits ``max_lines``. The cap must never *drop* content —
    the rhythm inflates line counts, and clamp_lines truncates."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    while len(lines) > max_lines:
        lines[-2:] = [", ".join(lines[-2:])]
    return "\n".join(lines)


def chat_rhythm(text: str, max_lines: Optional[int] = None) -> str:
    """Sentence separators become line breaks — replaced, not kept before the break.

    Quoted/code spans are never split. With ``max_lines`` the result is repacked to fit, so the
    group's line cap cannot eat content that the punctuation split inflated.
    """
    parts = _PROTECT_RE.split(text or "")
    joins = {}
    for i in range(1, len(parts), 2):
        if not _EMOTICON_RE.fullmatch(parts[i]):
            continue
        previous = parts[i - 1]
        boundary = next((m for pattern in (_DOT_BREAK_RE, _SEMI_RE, _ELLIPSIS_BREAK_RE, _QUEST_BREAK_RE)
                         for m in pattern.finditer(previous) if m.end() == len(previous)), None)
        if boundary:
            # A trailing face belongs to that sentence, rather than becoming an
            # orphan line. Break after the face when another sentence follows.
            punctuation = boundary.group(0).strip()
            token = f"\x00FACEJOIN{i}\x00"
            joins[token] = ("" if punctuation in {".", ";"} else punctuation) + " "
            parts[i - 1] = previous[:boundary.start()] + token
            parts[i + 1] = re.sub(r"^[ \t]+(?=\S)", "\n", parts[i + 1])
    for i in range(0, len(parts), 2):
        seg = _DASH_RE.sub("\n", parts[i])
        seg = _SEMI_RE.sub("\n", seg)
        seg = _ELLIPSIS_BREAK_RE.sub(r"\1\n", seg)
        seg = _QUEST_BREAK_RE.sub(r"\1\n", seg)
        seg = _NUMBERED_ABBREV_RE.sub(
            lambda m: m.group(0)[:-1] + _NUMBERED_ABBREV_TOKEN, seg)
        seg = _DOT_BREAK_RE.sub("\n", seg)
        seg = seg.replace(_NUMBERED_ABBREV_TOKEN, ".")
        parts[i] = _LINE_EDGE_RE.sub("\n", seg)
    out = "".join(parts)
    for token, value in joins.items():
        out = out.replace(token, value)
    if max_lines is not None:
        out = _pack_lines(out, max_lines)
    return _drop_trailing_separator(out)


def _english_script(text):
    return "".join(" " if char.isalpha() and "LATIN" not in unicodedata.name(char, "") else char for char in text)


def shape_group_reply(text: str) -> str:
    """Apply the group surface contract: emoji allowlist, no markdown, configured language, no personal
    details, no mechanical AI tells, chat line rhythm, line cap (``luna.output.max_lines``)."""
    strip_all, allowed = emoji_policy()
    max_lines = group_max_lines()
    if strip_all:
        text = strip_emoji(text or "")
    elif allowed is not None:  # None = emoji_filter: false, leave every emoji alone
        text = keep_only_allowed_emoji(text or "", allowed)
    text = strip_markdown(text)
    if output_config().get("language", "auto") == "english":
        text = _english_script(text).strip()
        if not text:
            return ENGLISH_ONLY_FALLBACK
    text = redact_personal_details(text)
    if output_config().get("style_filter", False):
        text = de_ai_text(text)
        if output_config().get("sentence_breaks", True):
            text = chat_rhythm(text, max_lines=max_lines)
    return bound_group_size(clamp_lines(normalize_whitespace(text), max_lines=max_lines))


def shape_group_reply_minimal(text: str) -> str:
    """Small subset of the group contract, for use when the full pipeline has failed.

    Excludes the configurable emoji allowlist and rhythm/style passes. Configuration access uses
    its safe fallback, because the caller is already handling an exception.
    Everything here is invariant 6 policy that must hold even in the degraded path: emoji stripped
    entirely, no markdown, configured language, personal details redacted, and the *configured* line cap
    (not the module default).
    """
    out = strip_emoji(text or "")
    out = strip_markdown(out)
    if output_config().get("language", "auto") == "english":
        out = _english_script(out).strip()
        if not out:
            return ENGLISH_ONLY_FALLBACK
    out = redact_personal_details(out)
    return bound_group_size(clamp_lines(normalize_whitespace(out), max_lines=group_max_lines()))


def shape_dm_reply(text: str) -> str:
    """Preserve the chosen voice/formatting unless casual-style rewriting is enabled."""
    if output_config().get("style_filter", False):
        out = de_ai_text(text or "")
        if output_config().get("sentence_breaks", True):
            out = chat_rhythm(out)
        return normalize_whitespace(out)
    return (text or "").strip()


def expand_abbreviations(text: str) -> str:
    """Expand abbreviations for TTS. Word-boundary aware for the dotted forms."""
    def _sub(match: re.Match) -> str:
        return _TTS_ABBREVIATIONS[match.group(0).lower()]

    return _TTS_RE.sub(_sub, text or "")


def shape_for_surface(text: str, surface: str, *, for_tts: bool = False) -> str:
    """Dispatch by surface (``group`` / ``dm`` / ``cli``)."""
    # Expand BEFORE shaping: the chat rhythm drops sentence-final dots, and the TTS table keys
    # on the dotted forms ("etc." → "and so on").
    if for_tts:
        text = expand_abbreviations(text or "")
    if surface == "group":
        out = shape_group_reply(text)
    else:
        out = shape_dm_reply(text)
    return out


def contains_farsi(text: str) -> bool:
    """True if the text contains Arabic/Persian script (English-only guard)."""
    return bool(_FARSI_RE.search(text or ""))


def guard_english(text: str, fallback: Optional[str] = None) -> Optional[str]:
    """Return ``fallback`` (or ``None``) when the draft is not English.

    Callers decide what to do with a non-English draft (regenerate, drop, or flag); this only
    detects it deterministically.
    """
    if _english_script(text or "") != (text or ""):
        return fallback
    return text


def bound_group_size(text):
    # One Telegram delivery, including UTF-16 surrogate pairs. Max is deliberately below 4096.
    try:
        limit = min(3500, max(80, int(output_config().get("max_chars", 1200))))
    except (TypeError, ValueError):
        limit = 1200
    encoded = text.encode("utf-16-le")
    if len(encoded) // 2 <= limit:
        return text
    return encoded[:(limit - 1) * 2].decode("utf-16-le", errors="ignore").rstrip() + "…"
