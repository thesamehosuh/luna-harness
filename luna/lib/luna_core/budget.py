"""Recall budget enforcement.

The 58,335-char prefetch that had to be dumped to a file is the bug this fixes: recall is *hard*
bounded, relevance-ranked, and truncated deterministically with a visible marker. Nothing downstream
may emit an unbounded memory block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

TRUNCATION_MARKER = "\n[…recall truncated to fit budget…]"
CHARS_PER_TOKEN = 4  # rough; good enough for a ceiling


@dataclass
class BudgetResult:
    text: str
    chars: int
    truncated: bool = False
    dropped: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {"chars": self.chars, "truncated": self.truncated, "dropped": self.dropped}


def approx_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def _cut_at_boundary(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    head = text[:limit]
    for sep in ("\n\n", "\n", ". ", " "):
        idx = head.rfind(sep)
        if idx > limit * 0.6:
            return head[:idx].rstrip()
    return head.rstrip()


def enforce_budget(
    text: str,
    *,
    max_chars: int,
    marker: str = TRUNCATION_MARKER,
) -> BudgetResult:
    """Hard-clamp ``text`` to ``max_chars`` (marker included)."""
    text = text or ""
    if max_chars <= 0:
        return BudgetResult(text="", chars=0, truncated=bool(text), dropped=1 if text else 0)
    if len(text) <= max_chars:
        return BudgetResult(text=text, chars=len(text))

    room = max_chars - len(marker)
    if room <= 0:
        return BudgetResult(text=marker[:max_chars], chars=min(max_chars, len(marker)),
                            truncated=True, dropped=1)
    kept = _cut_at_boundary(text, room)
    out = kept + marker
    return BudgetResult(text=out, chars=len(out), truncated=True, dropped=1)


def rank_sections(
    sections: Sequence[Tuple[float, str]],
    *,
    max_chars: int,
    marker: str = TRUNCATION_MARKER,
    joiner: str = "\n\n",
) -> BudgetResult:
    """Greedily include highest-scoring sections until ``max_chars`` is reached.

    ``sections`` is ``[(score, text), ...]``; higher score = more relevant. Ties keep input order.
    """
    if max_chars <= 0:
        return BudgetResult(text="", chars=0, truncated=bool(sections), dropped=len(sections))

    indexed = sorted(
        enumerate(sections), key=lambda pair: (-pair[1][0], pair[0])
    )
    chosen: List[str] = []
    used = 0
    dropped = 0
    for _, (_score, text) in indexed:
        text = (text or "").strip()
        if not text:
            continue
        extra = len(joiner) if chosen else 0
        if used + extra + len(text) > max_chars:
            dropped += 1
            continue
        chosen.append(text)
        used += extra + len(text)

    if not chosen:
        # Nothing fit whole: hard-truncate the single best section.
        best = max(sections, key=lambda s: s[0], default=(0.0, ""))[1]
        return enforce_budget(best, max_chars=max_chars, marker=marker)

    text = joiner.join(chosen)
    return BudgetResult(text=text, chars=len(text), truncated=bool(dropped), dropped=dropped)
