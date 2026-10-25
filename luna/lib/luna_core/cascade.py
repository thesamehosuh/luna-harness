"""The self-wake cascade — rare by default, with a semantic "directed at Luna" path.

Design informed by the TypeSafe docs (https://docs.typesafe.ai):

- **Atomic questions, composed in code.** No question hides several judgments.
- **Structured state.** Named fields referenced by path; unrelated state causes context rot.
- **Confidence is a second axis.** Choice/Score answers carry ``confidence``; we gate on it.
- **No structural invariants.** Never assume ``P(not x) = 1 - P(x)``.
- **No math/date reasoning in the model.** Timing and weighting live in code.

Two ways Luna can speak unprompted:

- **Directed** — jev judges the message is addressed to Luna (``addressed_to_luna`` high) even
  without a formal Telegram mention. This *replaces the literal "luna" word trigger* with a semantic
  one. Formal mentions / replies-to-Luna are handled reactively by the gateway and are marked
  ``triggered`` so they never reach here.
- **Ambient self-wake** — a rare, well-timed interjection (silence by default).

Stage 0  deterministic pre-filters (free, no jev)
Stage 1  one jev batch of atomic questions over a bounded structured state
Stage 2  deterministic composition (directed | message | reaction | silent)
Stage 3  hard rarity budget (:mod:`luna_core.wakes`)
Stage 4  the wake itself (``inject_message`` / ``platform_actions.add_reaction``)
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .jev import JevClient, JevError, choice, noul, score
from .wakes import DIRECTED, MESSAGE, REACTION, WakeBudget, WakePolicy

# Question ids
ADDRESSED = "addressed_to_luna"      # composed in code from the two atomic signals below
ADDRESSED_NAME = "named_luna"        # atomic: does the text name Luna?
ADDRESSED_DIRECT = "directly_addressed"  # atomic: is it aimed at Luna specifically?
ADD_VALUE = "luna_could_add_value"
OPEN_Q = "has_open_question_luna_can_answer"
TOPIC_FIT = "topic_fits_luna"
REDUNDANT = "would_be_redundant"
VENTING = "someone_is_venting"
SENSITIVE = "topic_is_sensitive"
PRIVATE = "topic_is_private"
INTERRUPTION = "interruption_cost"
TIMELINESS = "timeliness"
CONTRIBUTION = "contribution_type"
REACTION_FIT = "reaction_would_fit"
REACTION_EMOJI = "reaction_emoji"
REACTION_FRESH = "reaction_would_feel_fresh"
REQUESTS_REACTION = "requests_reaction"
MESSAGE_FIT = "message_would_fit"

# The three allowed reactions and what each means. 😭 is the versatile, most-used one.
REACTION_CRITERIA = {
    "👍": "agreeing with a serious point, or acknowledging something that matters — use only for "
          "serious or sincere messages, not funny ones",
    "🤣": "a deliberate joke, a punchline, or something genuinely funny — use when the message is "
          "trying to be funny and lands",
    "😭": "unhinged, chaotic, or ranting messages, and over-the-top or absurd reactions — the "
          "catch-all, most-used reaction",
}

LUNA_BLURB = "A companion in this room."

# How the *room* talks (not Luna's persona). Configured per deployment via
# ``luna.ambient.room_register``; this neutral description is the product default.
DEFAULT_ROOM_REGISTER = (
    "a private group chat. People talk casually and informally with each other."
)

_URL_RE = re.compile(r"https?://\S+")
_WORD_RE = re.compile(r"[^\W_]", re.UNICODE)

_INTERRUPTION_LABELS = ["welcome", "neutral", "unwelcome"]
_TIMELINESS_LABELS = ["too late", "just right", "premature"]


@dataclass
class CascadeConfig:
    # Stage 0
    min_new_messages: int = 3
    min_minutes_since_luna: float = 10.0
    min_candidate_chars: int = 3
    # Stage 1
    state_max_chars: int = 8000
    recent_lines: int = 20
    # Directed path (semantic replacement for the literal word trigger)
    directed_min_addressed: float = 0.70
    # Ambient message weights
    w_add_value: float = 0.35
    w_open_question: float = 0.20
    w_topic_fit: float = 0.15
    w_low_interruption: float = 0.15
    w_low_redundant: float = 0.10
    w_low_venting: float = 0.05
    # Ambient message gates — far stricter than reactions; a message wake is rare.
    # `message_min_value`/`message_min_fit` are calibrated from a 79-message real replay: jev's
    # "would speaking up be welcome?" answer is conservative (median 0.37, p90 0.42, max 0.47), so a
    # 0.85/0.70 pair could never fire. These bars admit ~1-2% of messages, which is still rare.
    message_min_value: float = 0.60
    # `message_would_fit` is the dedicated "would speaking up be welcome?" judgment. The old
    # `best_action` gate returned `silent` on ~98% of real messages, which made this tier
    # unreachable; that question has been removed entirely.
    message_min_fit: float = 0.42
    # A reaction must not swallow a genuine question Luna could answer: when the candidate is a real
    # open question at/above this, the message tier is preferred and the reaction yields.
    # On the reworded question, small talk scores ~0.02 and genuine questions 0.59-0.90, so 0.55
    # cleanly separates them. The old permissive wording scored both ~0.9, which made this gate
    # fire on ordinary chatter.
    reaction_yield_open_question: float = 0.55
    # …and only if she would actually add something by answering.
    reaction_yield_add_value: float = 0.45
    message_max_addressed: float = 0.25
    message_max_sensitive: float = 0.20
    message_max_private: float = 0.20
    message_max_venting: float = 0.30
    safety_max_sensitive: float = 0.60
    safety_max_private: float = 0.60
    # "Just right" timing is the middle Score level; jev returns a probability-weighted score that
    # lands between levels (live values are 1.0–1.2, never exactly 1.0), so gate on a band around the
    # middle level rather than equality (docs: score levels are weak in numerical calibration).
    timeliness_center: float = 1.0
    timeliness_band: float = 0.5
    # Reaction gates (low-key; may fit rants, so no venting/sensitive gate — only private).
    # A dedicated judgment (`reaction_would_fit`) decides whether a reaction fits, rather than a
    # general "what should Luna do" question. Thresholds are tuned on real room history
    # (luna/tools/jev_replay.py).
    reaction_min_fit: float = 0.66
    # jev's emoji_choice confidence has median ~0.49 and sat exactly on the old 0.50 bar, silently
    # rejecting 51% of otherwise-firing reactions. The allow-list already constrains the emoji to the
    # operator-approved set, so a less-certain pick is still safe; fit + freshness are the real gates.
    reaction_min_emoji_confidence: float = 0.35
    # Reaction gates (low-key). Per the plan, reactions are still gated on sensitive topics (and only
    # private) so a sensitive message never becomes a wake in any tier. Venting is intentionally NOT
    # gated here — reacting to a rant is a low-key, on-tone move, not an interjection.
    # ``reaction_min_value`` is deliberately LOW: `value` is the text-message composite (weighted for
    # "should she write something"), so holding a reaction to the same bar starved the tier. The real
    # brakes for reactions are `reaction_would_fit` and `reaction_would_feel_fresh`.
    reaction_min_value: float = 0.35
    reaction_max_private: float = 0.40
    # With the reworded question a joke scores ~0.20 and real distress 0.66-0.86, so 0.40 sits
    # cleanly between them. The old wording rated everything 0.93-0.98 and blocked legitimate
    # reactions to dark jokes.
    reaction_max_sensitive: float = 0.40
    # A message that names Luna but asks nothing still deserves a low-key reaction rather than a
    # text reply. If there IS an open question, she must answer it instead of reacting.
    reaction_max_open_question: float = 0.50
    # jev also judges freshness (repetition), given Luna's recent activity in the state.
    # Measured over 118 live verdicts: jev's freshness answer never exceeded 0.48 (median 0.37)
    # because the state had no cadence for it to judge against, so a 0.55 bar was a permanent
    # lockout. 0.43 is ~1 reaction per 19 messages. The real anti-spam guard is the code-level
    # reaction cooldown (WakePolicy), which does not depend on the model's judgement.
    reaction_min_freshness: float = 0.43
    # An explicit request ("react to this") outranks the directed-reply branch: the human asked for a
    # reaction, so it must not be answered with words. Freshness/value gates do not apply.
    reaction_request_min: float = 0.70

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Candidate:
    chat_id: str
    message_id: str
    text: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    timestamp: Optional[str] = None
    is_bot: bool = False
    addressed_to_luna: bool = False
    reply_to_luna: bool = False
    reply_to_message_id: Optional[str] = None
    pending_wake_same_thread: bool = False


@dataclass
class Stage0Context:
    new_messages_since_luna: int
    minutes_since_luna: float


@dataclass
class Decision:
    action: str = "silent"  # 'message' | 'reaction' | 'silent'
    value: float = 0.0
    reason: str = ""
    contribution_type: str = "silent"
    emoji: Optional[str] = None
    emoji_choice: Optional[str] = None
    directed: bool = False
    chat_id: Optional[str] = None
    target_message_id: Optional[str] = None
    scores: Dict[str, float] = field(default_factory=dict)
    stage: str = ""
    jev_route: str = ""          # 'free' | 'local' | 'paid' — cost class of the jev route that answered
    target_user: str = ""        # who said the message being judged
    thread_id: str = ""
    source_timestamp: str = ""
    source_digest: str = ""
    source_revision: str = ""
    target_text: str = ""        # what that message said (truncated for display)

    @property
    def should_wake(self) -> bool:
        return self.action in (MESSAGE, REACTION)

    @property
    def wake_kind(self) -> str:
        if self.directed:
            return DIRECTED
        return self.action if self.action in (MESSAGE, REACTION) else "silent"


def is_substantive(text: str, *, min_chars: int = 15) -> bool:
    """Reject only-emoji / only-link / too-short messages."""
    stripped = _URL_RE.sub("", text or "").strip()
    return len(_WORD_RE.findall(stripped)) >= min_chars


# The gateway records media-only messages as a single bracketed placeholder line (e.g.
# "[video 'x.mp4' saved at: /path]"). A tap on a GIF/sticker/video feels robotic and reads as spam,
# so the reaction tier skips these. They can still earn a *reply* if real text rides along.
_MEDIA_PLACEHOLDER_RE = re.compile(
    r"^\s*\[(?:video|image|photo|animation|gif|sticker|voice|audio|document|file)\b[^\]]*\]\s*$",
    re.IGNORECASE,
)


def is_media_only(text: str) -> bool:
    """True when the message is nothing but a media placeholder line (no real content)."""
    return bool(_MEDIA_PLACEHOLDER_RE.match(text or ""))


def prefilter(
    candidate: Candidate,
    ctx: Stage0Context,
    *,
    config: CascadeConfig,
    budget: WakeBudget,
    now: datetime,
    reactions_enabled: bool = False,
) -> Tuple[bool, str]:
    """Stage 0 — cheap, universal filters only.

    The ambient timing gates (``min_new_messages`` / ``min_minutes_since_luna``) are **not** here:
    they must not block a *directed* message, and we don't know whether a message is directed until
    jev answers. They are applied to the ambient message branch in :func:`compose` instead.
    """
    if candidate.is_bot:
        return False, "bot author"
    if candidate.addressed_to_luna or candidate.reply_to_luna:
        return False, "formal mention (reactive, handled by the gateway)"
    if not is_substantive(candidate.text, min_chars=config.min_candidate_chars):
        return False, "not substantive"
    if candidate.pending_wake_same_thread:
        return False, "pending wake for thread"

    ok_directed, _ = budget.can_wake(DIRECTED, now)
    ok_msg, reason_msg = budget.can_wake(MESSAGE, now)
    ok_rx, _ = budget.can_wake(REACTION, now) if reactions_enabled else (False, "reactions off")
    if not (ok_directed or ok_msg or ok_rx):
        return False, f"rarity budget: {reason_msg}"
    return True, "ok"


def build_state(
    candidate: Candidate,
    recent: Sequence[Tuple[str, ...]],
    *,
    config: CascadeConfig,
    luna_blurb: Optional[str] = None,
    room_register: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a bounded **structured** state. Named fields are referenced by path in instructions.

    ``recent`` items are ``(name, text)`` or ``(name, text, reply_to_name)``; reply edges are
    preserved so jev can see the shape of the discussion, not just a flat transcript.

    ``room_register`` is the room's voice (how people talk there) — the deployment's
    ``luna.ambient.room_register``; ``None``/empty falls back to :data:`DEFAULT_ROOM_REGISTER`.

    ``extra`` merges additional named fields (e.g. ``luna_recent_activity``) computed in code.
    """
    recent_items: List[Dict[str, Any]] = []
    for item in list(recent)[-config.recent_lines:]:
        name = item[0] if len(item) > 0 else "someone"
        text = item[1] if len(item) > 1 else ""
        entry: Dict[str, Any] = {"from": name, "text": (text or "").strip()[:300]}
        if len(item) > 2 and item[2]:
            entry["reply_to"] = item[2]
        recent_items.append(entry)

    state: Dict[str, Any] = {
        "luna": luna_blurb if luna_blurb is not None else character_brief(),
        "room": {
            "chat_id": candidate.chat_id,
            "kind": "private friend group",
            "register": (room_register or "").strip() or DEFAULT_ROOM_REGISTER,
        },
        "recent_messages": recent_items,
        "candidate": {
            "from": candidate.user_name or candidate.user_id or "unknown",
            "text": (candidate.text or "").strip()[:600],
        },
    }
    if extra:
        state.update(extra)
    while recent_items and len(json.dumps(state, ensure_ascii=False)) > config.state_max_chars:
        recent_items.pop(0)
        state["recent_messages"] = recent_items
    # A user persona, voice or extra field must not defeat the cascade's total input budget.
    for parent, key in [(state, "luna"), (state["room"], "register"), (state["candidate"], "from"), (state["candidate"], "text")]:
        while len(json.dumps(state, ensure_ascii=False)) > config.state_max_chars and parent.get(key):
            parent[key] = parent[key][:max(0, len(parent[key]) // 2)]
    for key in list(extra or {}):
        if len(json.dumps(state, ensure_ascii=False)) > config.state_max_chars:
            state.pop(key, None)
    return state


def build_questions(reactions: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Stage 1 — atomic questions, one batch. ``reactions`` adds the constrained emoji choice."""
    questions = [
        noul(ADDRESSED_NAME,
             "Does `candidate.text` name Luna or a clear variant of her name (e.g. 'luna', 'Luuuna')?",
             {"true": "names Luna", "false": "does not name Luna"}),
        noul(ADDRESSED_DIRECT,
             "Does `candidate.text` directly address Luna with a question or instruction aimed at her "
             "specifically, even if it does not name her? Treat an initial, a nickname, or a stand-in "
             "for her (e.g. 'someone whose name starts with L' when Luna is the only L in the room) as "
             "aimed at Luna. Answer false when it is aimed at the room in general or at nobody in "
             "particular.",
             {"true": "aimed at Luna specifically", "false": "not aimed at Luna"}),
        noul(ADD_VALUE,
             "Could Luna add something concrete and useful here: an answer, a fact, a correction, "
             "fitting humour, or support?",
             {"true": "could add real value", "false": "nothing to add"}),
        noul(MESSAGE_FIT,
             "If Luna spoke in the group right now — unprompted, in one short message — would it be a "
             "genuine contribution that the group would welcome, or would it feel like butting in?",
             {"true": "worth speaking up", "false": "would be butting in"}),
        noul(OPEN_Q,
             "Is `candidate.text` itself a question that nobody has answered yet — something someone "
             "actually asked? A statement, a joke, small talk, or a complaint is not a question.",
             {"true": "an unanswered question", "false": "not a question"}),
        noul(TOPIC_FIT,
             "Does the topic of `candidate.text` fit Luna's persona and knowledge as a member of this "
             "friend group?",
             {"true": "fits", "false": "does not fit"}),
        noul(REDUNDANT,
             "Would a reply from Luna be redundant because the point has already been made or answered "
             "in `recent_messages`?",
             {"true": "already covered", "false": "not covered"}),
        noul(VENTING,
             "Is someone in `candidate.text` venting or in an emotional state where a comment from "
             "Luna would be unwelcome?",
             {"true": "venting or upset", "false": "not venting"}),
        noul(SENSITIVE,
             "Would a reaction to `candidate.text` be unwelcome because someone is genuinely upset, "
             "unwell, or in a real crisis? This room jokes about crimes, jail, death and other awful "
             "things as a matter of course, so a bleak or shocking statement that nobody is actually "
             "upset about does not count as sensitive.",
             {"true": "genuinely sensitive", "false": "not sensitive"}),
        noul(PRIVATE,
             "Does `candidate.text` reveal or invite discussion of information the speaker likely wants "
             "kept private (explicit secrets, or sensitive health, money, relationship, location, or "
             "credential details)? Ordinary personal updates, achievements, family plans, preferences, "
             "and casual conversation are not private.",
             {"true": "information likely intended to stay private", "false": "ordinary personal content"}),
        score(INTERRUPTION,
              "How welcome would it be for Luna to chime in on `candidate.text` right now, as one of "
              "the people in the conversation?",
              _INTERRUPTION_LABELS),
        score(TIMELINESS,
              "Is this the right moment for Luna to speak, given `candidate.text` and `recent_messages`?",
              _TIMELINESS_LABELS),
        choice(CONTRIBUTION,
               "If Luna does contribute, what kind of contribution is it?",
               {"answer": "answers a question", "fact": "adds a fact", "correction": "corrects something",
                "humor": "fits the humour", "support": "offers support", "silent": "nothing"}),
    ]
    if reactions:
        questions.append(noul(REQUESTS_REACTION,
                              "Does `candidate.text` explicitly ask Luna to react to a message (using "
                              "words like 'react', 'reaction', 'add an emoji'), rather than to reply "
                              "in words?",
                              {"true": "asks for a reaction", "false": "does not ask for a reaction"}))
        questions.append(noul(REACTION_FIT,
                              "Does `candidate.text` carry enough content for Luna's reaction to "
                              "actually say something — a joke, a shared moment, something that "
                              "landed, or a feeling worth acknowledging? A reaction to a message with "
                              "no real content (a test ping, a single filler word, or an empty "
                              "message) says nothing, even though a reaction could technically be "
                              "attached to it.",
                              {"true": "a reaction would say something",
                               "false": "a reaction would say nothing"}))
        criteria = {e: REACTION_CRITERIA.get(e, "") for e in reactions}
        questions.append(choice(REACTION_EMOJI,
                                "If Luna were to react to `candidate.text`, which single reaction fits "
                                "best? Do not default to 👍: use 😭 for chaotic, absurd, ranting, or "
                                "funny messages and 🤣 only for genuinely funny ones; reserve 👍 for "
                                "serious, sincere agreement.",
                                criteria))
        questions.append(noul(REACTION_FRESH,
                              "Would a reaction from Luna right now feel fresh, given "
                              "`luna_recent_activity`? Answer false if Luna has reacted recently or "
                              "often enough that another reaction would feel repetitive.",
                              {"true": "would feel fresh", "false": "would feel repetitive"}))
    name, aliases = character_identity()
    def renamed(value):
        if isinstance(value, str):
            return value.replace("Luuuna", name).replace("luna'", name + "'").replace("Luna", name).replace("starts with L", "starts with " + name[0]).replace("only L in", "only " + name[0] + " in")
        if isinstance(value, dict):
            return {key: renamed(item) for key, item in value.items()}
        if isinstance(value, list):
            return [renamed(item) for item in value]
        return value
    questions = renamed(questions)
    if aliases:
        questions[0]["instructions"] = questions[0].get("instructions", "") + " Configured aliases: " + ", ".join(aliases)
    return questions


def character_identity():
    from luna_core import config_read
    from luna_core.runtime import home
    configured = config_read.section("luna", "character", default={}) or {}
    try:
        first = (home() / "SOUL.md").read_text().splitlines()[0]
        title = first[2:].strip()[:80] if first.startswith("# ") else "Companion"
    except (OSError, IndexError):
        title = "Companion"
    name = str(configured.get("name") or title).strip()[:80] or "Companion"
    return name, [str(value) for value in configured.get("aliases", [])]


def character_brief():
    from luna_core.runtime import home
    name, aliases = character_identity()
    try:
        soul = (home() / "SOUL.md").read_text()[:1500]
    except OSError:
        soul = "A companion in this room."
    return f"Companion name: {name}. Aliases: {', '.join(aliases)}. Persona:\n{soul}"


def _prob(answers: Dict[str, Any], qid: str, default: float = 0.0) -> float:
    ans = answers.get(qid)
    return default if ans is None else float(ans.as_probability())


def _num(answers: Dict[str, Any], qid: str, labels: Optional[List[str]] = None,
         default: float = 2.0) -> float:
    ans = answers.get(qid)
    if ans is None:
        return default
    value = ans.value
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if labels:
        for i, label in enumerate(labels):
            if text == str(label).lower():
                return float(i)
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _label(answers: Dict[str, Any], qid: str, default: str = "") -> str:
    ans = answers.get(qid)
    return default if ans is None else str(ans.value)


def _confidence(answers: Dict[str, Any], qid: str, default: float = 1.0) -> float:
    ans = answers.get(qid)
    if ans is None or ans.confidence is None:
        return default  # the API always returns confidence for Choice/Score
    return float(ans.confidence)


def compose(
    answers: Dict[str, Any],
    *,
    config: CascadeConfig,
    reactions_enabled: bool = False,
    allowed_reactions: Optional[Sequence[str]] = None,
    ctx: Optional[Stage0Context] = None,
    candidate_text: str = "",
) -> Decision:
    """Stage 2 — deterministic composition. Missing answers fail closed (silent)."""
    required = [ADD_VALUE, OPEN_Q, TOPIC_FIT, REDUNDANT, VENTING, SENSITIVE, PRIVATE,
                ADDRESSED_NAME, ADDRESSED_DIRECT, INTERRUPTION, TIMELINESS]
    if any(q not in answers for q in required):
        return Decision(action="silent", reason="incomplete jev answers", stage="stage2")

    from luna_core.jev import validate_answers
    try:
        validate_answers(answers, build_questions(allowed_reactions if reactions_enabled else None), require_all=False)
    except JevError:
        return Decision(action="silent", reason="invalid jev answers", stage="stage2")

    add_value = _prob(answers, ADD_VALUE)
    open_q = _prob(answers, OPEN_Q)
    topic_fit = _prob(answers, TOPIC_FIT)
    redundant = _prob(answers, REDUNDANT)
    venting = _prob(answers, VENTING)
    sensitive = _prob(answers, SENSITIVE)
    private = _prob(answers, PRIVATE)
    # `addressed` is composed in code from two atomic judgments (docs: don't hide several judgments
    # in one question). Either signal alone is enough to count as addressed.
    named = _prob(answers, ADDRESSED_NAME)
    direct = _prob(answers, ADDRESSED_DIRECT)
    addressed = max(named, direct)
    interruption = _num(answers, INTERRUPTION, _INTERRUPTION_LABELS)
    timeliness = _num(answers, TIMELINESS, _TIMELINESS_LABELS)
    contribution = _label(answers, CONTRIBUTION, "silent")
    # The dedicated "would speaking up be welcome?" judgment. Independent of `best_action`, which is
    # biased to silence by the persona and returned `silent` on 74/75 real messages.
    message_would_fit = _prob(answers, MESSAGE_FIT, 0.0)
    # A tap on a GIF/sticker/video placeholder reads as robotic — the reaction tier skips media-only.
    media_only = is_media_only(candidate_text)

    value = (
        config.w_add_value * add_value
        + config.w_open_question * open_q
        + config.w_topic_fit * topic_fit
        + config.w_low_interruption * (1.0 - min(interruption, 2.0) / 2.0)
        + config.w_low_redundant * (1.0 - redundant)
        + config.w_low_venting * (1.0 - venting)
    )
    scores = {
        "add_value": add_value, "open_question": open_q, "topic_fit": topic_fit,
        "redundant": redundant, "venting": venting, "sensitive": sensitive, "private": private,
        "addressed": addressed, "addressed_name": named, "addressed_direct": direct,
        "interruption": interruption, "timeliness": timeliness, "message_would_fit": message_would_fit,
        "value": round(value, 4),
    }

    base = Decision(value=round(value, 4), scores=scores, stage="stage2",
                    contribution_type=contribution)

    if sensitive >= config.safety_max_sensitive or private >= config.safety_max_private:
        base.action = "silent"
        base.reason = "sensitive/private safety gate"
        return base

    # Reaction inputs are computed up front: an explicit reaction request is decided before the
    # directed branch, so it must not be answered with words.
    if reactions_enabled and (REACTION_FRESH not in answers or REACTION_FIT not in answers):
        # Reaction path was offered but not fully judged — fail closed.
        emoji, emoji_confidence, fresh, fit = "", 0.0, 0.0, 0.0
    else:
        emoji = _label(answers, REACTION_EMOJI, "") if reactions_enabled else ""
        emoji_confidence = _confidence(answers, REACTION_EMOJI, 0.0)
        fresh = _prob(answers, REACTION_FRESH, 0.0)
        fit = _prob(answers, REACTION_FIT, 0.0)
    allowed = list(allowed_reactions or [])
    # When the human names the emoji ("React with 👍"), use it instead of jev's pick — code, not model.
    if reactions_enabled:
        literal = next((e for e in allowed if e and e in (candidate_text or "")), None)
        if literal:
            emoji = literal
    requests_reaction = _prob(answers, REQUESTS_REACTION, 0.0) if reactions_enabled else 0.0
    base.emoji_choice = emoji or None
    scores["reaction_fit"] = fit
    scores["reaction_freshness"] = fresh
    scores["emoji_confidence"] = emoji_confidence
    scores["requests_reaction"] = requests_reaction

    # 0) Explicit reaction request outranks the directed reply: the human asked for a reaction, so
    # answering in words is wrong. Freshness and value gates do not apply to an explicit request.
    if (reactions_enabled
            and requests_reaction >= config.reaction_request_min
            and emoji in allowed
            and emoji_confidence >= config.reaction_min_emoji_confidence):
        base.action = REACTION
        base.emoji = emoji
        base.reason = "explicit reaction request"
        return base

    # 1) Directed: jev judges the message is addressed to Luna (semantic trigger). The semantic
    # judgment alone decides; no general "what should Luna do" signal may override "she was
    # addressed".
    if addressed >= config.directed_min_addressed:
        # …unless she was merely *named* (not asked anything) and a low-key reaction clearly fits.
        # A named message with no open question ("oh luna ive got a crush on you") reads better as a
        # tap than a paragraph; anything that actually asks something still gets a real reply.
        if (reactions_enabled
                and not media_only
                and open_q <= config.reaction_max_open_question
                and requests_reaction < config.reaction_request_min
                and fit >= config.reaction_min_fit
                and value >= config.reaction_min_value
                and private <= config.reaction_max_private
                and sensitive <= config.reaction_max_sensitive
                and emoji in allowed
                and emoji_confidence >= config.reaction_min_emoji_confidence
                and fresh >= config.reaction_min_freshness):
            base.action = REACTION
            base.emoji = emoji
            base.reason = "named but nothing to answer; reaction fits"
            return base
        base.action = MESSAGE
        base.directed = True
        base.reason = "addressed to companion (semantic trigger)"
        return base

    # 2) Ambient message: rare, well-timed, in the middle of the room. The timing gates live here
    # (not in Stage 0) so they never block a directed reply.
    #
    # The gate is `message_would_fit` — a dedicated "would speaking up be welcome?" judgment.
    # `value >= 0.60` is the real bar, so the tier stays rare.
    timing_ok = True
    if ctx is not None:
        timing_ok = (ctx.new_messages_since_luna >= config.min_new_messages
                     and ctx.minutes_since_luna >= config.min_minutes_since_luna)
    wake_message = (
        message_would_fit >= config.message_min_fit
        and value >= config.message_min_value
        and abs(timeliness - config.timeliness_center) <= config.timeliness_band
        and timing_ok
        and addressed <= config.message_max_addressed
        and sensitive <= config.message_max_sensitive
        and private <= config.message_max_private
        and venting <= config.message_max_venting
    )
    if wake_message:
        base.action = MESSAGE
        base.reason = "high-value, well-timed ambient contribution"
        return base

    # 3) Reaction: its own judgment (`reaction_would_fit`). Gated on sensitive + private; NOT on
    # venting (a rant reaction is low-key and on-tone, not an interjection). The value floor is low because `value` is weighted
    # for writing a message, not for tapping an emoji; `reaction_would_fit` + freshness are the real
    # fit and anti-spam brakes.
    #
    # YIELD: a tap must not swallow a real question. When the candidate is a genuine open question
    # (open_q at/above `reaction_yield_open_question`) that Luna could answer, a reaction is the wrong
    # response — words are. So the reaction defers and the message tier (or silence) owns it.
    question_owed_words = open_q >= config.reaction_yield_open_question
    wake_reaction = (
        reactions_enabled
        and not media_only
        and fit >= config.reaction_min_fit
        and value >= config.reaction_min_value
        and private <= config.reaction_max_private
        and sensitive <= config.reaction_max_sensitive
        and emoji in allowed
        and emoji_confidence >= config.reaction_min_emoji_confidence
        and fresh >= config.reaction_min_freshness
        and not (question_owed_words and add_value >= config.reaction_yield_add_value)
    )
    if wake_reaction:
        base.action = REACTION
        base.emoji = emoji
        base.reason = "low-key reaction"
        return base

    base.action = "silent"
    base.reason = "middle band / below threshold"
    return base


def decide(
    client: JevClient,
    *,
    candidate: Candidate,
    ctx: Stage0Context,
    recent: Sequence[Tuple[str, str]],
    config: Optional[CascadeConfig] = None,
    budget: Optional[WakeBudget] = None,
    now: Optional[datetime] = None,
    reactions_enabled: bool = False,
    allowed_reactions: Optional[Sequence[str]] = None,
    extra_state: Optional[Dict[str, Any]] = None,
    room_register: Optional[str] = None,
    before_jev=None,
) -> Decision:
    """Run stages 0–2. Stage 3 (budget) is re-checked by the caller before recording a wake."""
    config = config or CascadeConfig()
    now = now or datetime.now(timezone.utc)
    if budget is None:
        raise ValueError("decide() requires a WakeBudget")

    allowed, reason = prefilter(
        candidate, ctx, config=config, budget=budget, now=now, reactions_enabled=reactions_enabled
    )
    if not allowed:
        return Decision(action="silent", reason=f"stage0: {reason}", stage="stage0")

    if before_jev is not None and not before_jev():
        return Decision(action="silent", reason="judgement resource guard", stage="guard")
    state = build_state(candidate, recent, config=config, extra=extra_state, room_register=room_register)
    try:
        answers = client.ask(state, build_questions(allowed_reactions if reactions_enabled else None))
    except JevError as exc:
        return Decision(action="silent", reason=f"jev error (fail closed): {exc}", stage="stage1")
    except Exception as exc:  # never let a client bug crash the poller into a retry loop
        return Decision(action="silent", reason=f"jev error (fail closed): {type(exc).__name__}: {exc}",
                        stage="stage1")

    decision = compose(answers, config=config, reactions_enabled=reactions_enabled,
                       allowed_reactions=allowed_reactions, ctx=ctx,
                       candidate_text=candidate.text)
    decision.chat_id = candidate.chat_id
    decision.target_message_id = candidate.message_id

    # Stage 3 — the chosen wake kind may be capped even if another kind could wake.
    if decision.should_wake:
        ok, why = budget.can_wake(decision.wake_kind, now)
        if not ok:
            return replace(decision, action="silent", reason=f"stage3: {why}")
    return decision
