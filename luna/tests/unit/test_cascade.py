"""Self-wake cascade: pre-filters, structured state, composition math, gates, fail-closed."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from luna_core import db
from luna_core.cascade import (  # noqa: E501
    ADD_VALUE,
    ADDRESSED,
    ADDRESSED_DIRECT,
    ADDRESSED_NAME,
    CONTRIBUTION,
    INTERRUPTION,
    MESSAGE_FIT,
    OPEN_Q,
    PRIVATE,
    REACTION_EMOJI,
    REACTION_FIT,
    REACTION_FRESH,
    REDUNDANT,
    REQUESTS_REACTION,
    SENSITIVE,
    TIMELINESS,
    TOPIC_FIT,
    VENTING,
    Candidate,
    is_media_only,
    CascadeConfig,
    Stage0Context,
    build_questions,
    build_state,
    compose,
    decide,
    is_substantive,
    prefilter,
)
from luna_core.jev import JevAnswer
from luna_core.wakes import MESSAGE, REACTION, WakeBudget

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def budget(tmp_path):
    conn = db.connect(tmp_path / "luna-state.db")
    db.init_db(conn)
    yield WakeBudget(conn)
    conn.close()


def _answers(
    *,
    add_value=0.9,
    open_q=0.8,
    topic_fit=0.9,
    redundant=0.05,
    venting=0.05,
    sensitive=0.05,
    private=0.05,
    addressed_name=0.05,
    addressed_direct=0.05,
    addressed=None,
    interruption=0,
    timeliness=1,
    contribution="fact",
    reaction_emoji="😭",
    emoji_confidence=0.8,
    reaction_fresh=0.9,
    reaction_fit=0.7,
    requests_reaction=0.0,
    message_fit=0.0,
):
    def a(qid, value, conf=None):
        specs = {q['id']: q for q in build_questions(["👍", "🤣", "😭"])}
        return JevAnswer(id=qid, type=specs[qid]['type'], value=value, confidence=conf)

    # `addressed=` sets both atomic signals at once (the pre-split convenience).
    if addressed is not None:
        addressed_name = addressed_direct = addressed

    return {
        ADD_VALUE: a(ADD_VALUE, add_value),
        OPEN_Q: a(OPEN_Q, open_q),
        TOPIC_FIT: a(TOPIC_FIT, topic_fit),
        REDUNDANT: a(REDUNDANT, redundant),
        VENTING: a(VENTING, venting),
        SENSITIVE: a(SENSITIVE, sensitive),
        PRIVATE: a(PRIVATE, private),
        ADDRESSED_NAME: a(ADDRESSED_NAME, addressed_name),
        ADDRESSED_DIRECT: a(ADDRESSED_DIRECT, addressed_direct),
        INTERRUPTION: a(INTERRUPTION, interruption),
        TIMELINESS: a(TIMELINESS, timeliness),
        CONTRIBUTION: a(CONTRIBUTION, contribution),
        REACTION_EMOJI: a(REACTION_EMOJI, reaction_emoji, emoji_confidence),
        REACTION_FIT: a(REACTION_FIT, reaction_fit),
        REACTION_FRESH: a(REACTION_FRESH, reaction_fresh),
        REQUESTS_REACTION: a(REQUESTS_REACTION, requests_reaction),
        MESSAGE_FIT: a(MESSAGE_FIT, message_fit),
    }


def _candidate(**kw):
    base = dict(chat_id="-100", message_id="m1", text="anyone know a good pizza place nearby?")
    base.update(kw)
    return Candidate(**base)


def _ctx(**kw):
    base = dict(new_messages_since_luna=5, minutes_since_luna=30.0)
    base.update(kw)
    return Stage0Context(**base)


# -- stage 0 ----------------------------------------------------------------
@pytest.mark.parametrize(
    "cand,ctx,reason_part",
    [
        (_candidate(is_bot=True), _ctx(), "bot"),
        (_candidate(addressed_to_luna=True), _ctx(), "formal mention"),
        (_candidate(reply_to_luna=True), _ctx(), "formal mention"),
        (_candidate(text="🔥🔥"), _ctx(), "substantive"),
        (_candidate(pending_wake_same_thread=True), _ctx(), "pending"),
    ],
)
def test_prefilter_rejects(cand, ctx, reason_part, budget):
    allowed, reason = prefilter(cand, ctx, config=CascadeConfig(), budget=budget, now=NOW)
    assert allowed is False
    assert reason_part in reason


def test_prefilter_allows_timing_gated_messages(budget):
    """Ambient timing gates are NOT in Stage 0 — a possibly-directed message must still reach jev."""
    allowed, _ = prefilter(_candidate(), _ctx(new_messages_since_luna=0, minutes_since_luna=0.0),
                           config=CascadeConfig(), budget=budget, now=NOW)
    assert allowed is True


def test_prefilter_allows_clean_candidate(budget):
    allowed, reason = prefilter(_candidate(), _ctx(), config=CascadeConfig(), budget=budget, now=NOW)
    assert allowed is True and reason == "ok"


def test_is_substantive():
    assert is_substantive("hello there friend")
    assert not is_substantive("🔥🔥🔥")
    assert not is_substantive("https://example.com")
    assert not is_substantive("ok")


# -- stage 1 ----------------------------------------------------------------
def test_build_state_is_structured_and_bounded():
    recent = [(f"u{i}", "x" * 300) for i in range(100)]
    state = build_state(_candidate(), recent, config=CascadeConfig(state_max_chars=1000))
    assert isinstance(state, dict)
    assert state["candidate"]["text"].startswith("anyone know")
    assert state["room"]["chat_id"] == "-100"
    assert len(json.dumps(state, ensure_ascii=False)) <= 1000


def test_build_state_preserves_reply_edges():
    recent = [("Alex", "anyone up for pizza?", None), ("Babi", "always", "Alex")]
    state = build_state(_candidate(), recent, config=CascadeConfig())
    assert state["recent_messages"][0]["from"] == "Alex"
    assert state["recent_messages"][1]["reply_to"] == "Alex"


def test_build_state_includes_extra_fields():
    state = build_state(_candidate(), [], config=CascadeConfig(),
                        extra={"luna_recent_activity": "Luna has not reacted recently."})
    assert state["luna_recent_activity"].startswith("Luna has not reacted")


def test_room_register_is_configurable_not_hardcoded():
    """The room voice is deployment config (luna.ambient.room_register), never fixed code."""
    from luna_core.cascade import DEFAULT_ROOM_REGISTER

    default_state = build_state(_candidate(), [], config=CascadeConfig())
    assert default_state["room"]["register"] == DEFAULT_ROOM_REGISTER

    custom = build_state(_candidate(), [], config=CascadeConfig(),
                         room_register="  a loud gaming server. Everyone types in caps.  ")
    assert custom["room"]["register"] == "a loud gaming server. Everyone types in caps."

    # Empty/blank falls back to the neutral default rather than an empty register.
    fallback = build_state(_candidate(), [], config=CascadeConfig(), room_register="   ")
    assert fallback["room"]["register"] == DEFAULT_ROOM_REGISTER


def test_build_questions_has_expected_ids():
    ids = {q["id"] for q in build_questions()}
    assert {ADD_VALUE, OPEN_Q, TOPIC_FIT, REDUNDANT, VENTING, SENSITIVE, PRIVATE,
            ADDRESSED_NAME, ADDRESSED_DIRECT, INTERRUPTION, TIMELINESS,
            CONTRIBUTION, MESSAGE_FIT} == ids


def test_build_questions_reactions_add_ids():
    ids = {q["id"] for q in build_questions(["👍", "🤣", "😭"])}
    assert {REQUESTS_REACTION, REACTION_FIT, REACTION_EMOJI, REACTION_FRESH} <= ids


def test_noul_questions_use_true_false_criteria():
    for q in build_questions():
        if q["type"] == "noul" and "criteria" in q:
            assert set(q["criteria"]) <= {"true", "false"}


def test_private_question_excludes_ordinary_personal_updates():
    private = next(q for q in build_questions() if q["id"] == PRIVATE)
    assert "Ordinary personal updates" in private["instructions"]
    assert "family plans" in private["instructions"]
    assert "casual conversation" in private["instructions"]


# -- stage 2 ----------------------------------------------------------------
def test_compose_high_confidence_message_wakes():
    d = compose(_answers(message_fit=0.9), config=CascadeConfig())
    assert d.action == MESSAGE
    assert d.value >= 0.80
    assert d.contribution_type == "fact"


def test_compose_middle_band_is_silent():
    d = compose(_answers(add_value=0.5, open_q=0.4, topic_fit=0.5), config=CascadeConfig())
    assert d.action == "silent"
    assert d.value < 0.80


def test_compose_timeliness_not_just_right_blocks_message():
    assert compose(_answers(message_fit=0.9, timeliness=0), config=CascadeConfig()).action == "silent"
    assert compose(_answers(message_fit=0.9, timeliness=2), config=CascadeConfig()).action == "silent"


def test_compose_timeliness_between_levels_still_allows_message():
    """jev Score lands between levels (live values 1.0–1.2), so a band, not equality, gates timing."""
    assert compose(_answers(message_fit=0.9, timeliness=1.07), config=CascadeConfig()).action == MESSAGE
    assert compose(_answers(message_fit=0.9, timeliness=1.4), config=CascadeConfig()).action == MESSAGE
    assert compose(_answers(message_fit=0.9, timeliness=0.4), config=CascadeConfig()).action == "silent"


def test_compose_addressed_triggers_directed():
    d = compose(_answers(addressed=0.9), config=CascadeConfig())
    assert d.action == MESSAGE
    assert d.directed is True
    assert "directed" in d.reason or "addressed" in d.reason


def test_compose_addressed_from_either_atomic_signal():
    cfg = CascadeConfig()
    assert compose(_answers(addressed_name=0.9), config=cfg).directed is True
    assert compose(_answers(addressed_direct=0.9), config=cfg).directed is True
    assert compose(_answers(addressed_name=0.1, addressed_direct=0.1), config=cfg).directed is False


def test_compose_explicit_reaction_request_outranks_directed():
    """'React to this' names Luna (directed) but must produce a reaction, not a reply."""
    d = compose(_answers(addressed=0.97, requests_reaction=0.9, reaction_emoji="😭", emoji_confidence=0.8),
                config=CascadeConfig(), reactions_enabled=True, allowed_reactions=["👍", "🤣", "😭"])
    assert d.action == REACTION
    assert d.directed is False
    assert d.emoji == "😭"
    assert "explicit" in d.reason


def test_compose_explicit_reaction_uses_emoji_named_in_text():
    d = compose(_answers(addressed=0.97, requests_reaction=0.9, reaction_emoji="😭",
                         emoji_confidence=0.8),
                config=CascadeConfig(), reactions_enabled=True, allowed_reactions=["👍", "🤣", "😭"],
                candidate_text="React with 👍")
    assert d.action == REACTION
    assert d.emoji == "👍"


def test_compose_reaction_request_ignored_when_reactions_disabled():
    d = compose(_answers(addressed=0.97, requests_reaction=0.9), config=CascadeConfig(),
                reactions_enabled=False)
    assert d.action == MESSAGE and d.directed is True


def test_compose_ambient_message_blocked_by_timing():
    d = compose(_answers(), config=CascadeConfig(),
                ctx=Stage0Context(new_messages_since_luna=1, minutes_since_luna=2.0))
    assert d.action == "silent"


def test_compose_directed_bypasses_timing():
    """A directed message is answered even right after Luna spoke."""
    d = compose(_answers(addressed=0.9), config=CascadeConfig(),
                ctx=Stage0Context(new_messages_since_luna=0, minutes_since_luna=0.0))
    assert d.action == MESSAGE
    assert d.directed is True


def test_compose_low_addressed_does_not_direct():
    d = compose(_answers(addressed=0.3), config=CascadeConfig())
    assert d.action == "silent"


def test_compose_sensitive_private_venting_block_message():
    assert compose(_answers(sensitive=0.9), config=CascadeConfig()).action == "silent"
    assert compose(_answers(private=0.9), config=CascadeConfig()).action == "silent"
    assert compose(_answers(venting=0.9), config=CascadeConfig()).action == "silent"


def test_safety_gate_blocks_directed_sensitive_and_private_messages():
    assert compose(_answers(addressed=0.9, sensitive=0.7), config=CascadeConfig()).action == "silent"
    assert compose(_answers(addressed=0.9, private=0.7), config=CascadeConfig()).action == "silent"


def test_safety_gate_keeps_a_dark_joke_addressed_to_luna():
    decision = compose(
        _answers(addressed=0.9, sensitive=0.06, private=0.39, venting=0.12),
        config=CascadeConfig(),
    )
    assert decision.action == MESSAGE
    assert decision.directed is True


def test_compose_low_message_fit_blocks_message():
    """The message gate is `message_would_fit`, not `best_action` (which is biased to silence)."""
    assert compose(_answers(message_fit=0.3), config=CascadeConfig()).action == "silent"


def test_compose_ignores_biased_best_action():
    """`best_action == "silent"` must not veto a genuine contribution (74/75 real messages were silent)."""
    d = compose(_answers(message_fit=0.9),
                config=CascadeConfig())
    assert d.action == MESSAGE


REACTIONS = ["👍", "🤣", "😭"]


def test_compose_reaction_requires_enable_and_choice():
    answers = _answers(add_value=0.7, open_q=0.5, topic_fit=0.7)
    assert compose(answers, config=CascadeConfig(), reactions_enabled=False).action == "silent"
    d = compose(answers, config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == REACTION
    assert d.emoji == "😭"


def test_compose_reaction_emoji_must_be_allowed():
    answers = _answers(add_value=0.7, open_q=0.5, topic_fit=0.7,
                       reaction_emoji="💀")
    d = compose(answers, config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == "silent"


def test_compose_reaction_emoji_confidence_gate():
    answers = _answers(add_value=0.7, open_q=0.5, topic_fit=0.7,
                       emoji_confidence=0.1)
    d = compose(answers, config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == "silent"


def test_compose_reaction_allows_venting():
    """😭 is meant for rants — the reaction path must not be blocked by venting."""
    answers = _answers(add_value=0.7, open_q=0.5, topic_fit=0.7, venting=0.9)
    d = compose(answers, config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == REACTION


def test_compose_sensitive_blocks_reaction():
    """Required regression: a sensitive message must not wake in ANY tier (message or reaction)."""
    answers = _answers(add_value=0.7, open_q=0.5, topic_fit=0.7, sensitive=0.9)
    d = compose(answers, config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == "silent"


def test_compose_private_blocks_reaction():
    answers = _answers(add_value=0.7, open_q=0.5, topic_fit=0.7, private=0.9)
    d = compose(answers, config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == "silent"


def test_named_but_no_open_question_reacts_instead_of_replying():
    """'oh luna ive got a crush on you' names her but asks nothing -> a tap beats a paragraph."""
    d = compose(_answers(addressed=0.95, open_q=0.05, add_value=0.5, reaction_fit=0.85, reaction_emoji="😭", reaction_fresh=0.9,
                         emoji_confidence=0.8),
                config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == REACTION
    assert d.emoji == "😭"
    assert d.directed is False


def test_named_with_open_question_still_gets_a_reply():
    """If she is actually asked something, a reaction is not enough — she must answer."""
    d = compose(_answers(addressed=0.95, open_q=0.85, add_value=0.8, reaction_fit=0.85, reaction_emoji="😭", reaction_fresh=0.9,
                         emoji_confidence=0.8),
                config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == MESSAGE
    assert d.directed is True


def test_reaction_bar_is_independent_of_text_shaped_value():
    """A mid-range composite `value` (under the old 0.60 bar) must not starve a genuine reaction fit."""
    mid_value = _answers(add_value=0.6, open_q=0.2, topic_fit=0.5,
                         interruption=1, reaction_fit=0.9, reaction_emoji="🤣",
                         reaction_fresh=0.9, emoji_confidence=0.8)
    d = compose(mid_value, config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert 0.35 <= d.value < 0.60  # would have been starved by the old message-shaped bar
    assert d.action == REACTION


def test_compose_reaction_freshness_gate():
    """jev judges repetition: a stale/too-frequent reaction is suppressed."""
    answers = _answers(add_value=0.7, open_q=0.5, topic_fit=0.7,
                       reaction_fresh=0.1)
    d = compose(answers, config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == "silent"


def test_compose_reaction_fit_gate():
    """Reactions do not depend on the conservative `best_action`; their own judgment gates them."""
    answers = _answers(add_value=0.7, open_q=0.5, topic_fit=0.7,
                       reaction_fit=0.1)
    d = compose(answers, config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == "silent"


def test_compose_reaction_fires_on_fit_without_best_action():
    answers = _answers(add_value=0.7, open_q=0.5, topic_fit=0.7,
                       reaction_fit=0.9)
    d = compose(answers, config=CascadeConfig(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == REACTION
    assert d.emoji == "😭"


def test_compose_incomplete_answers_fail_closed():
    d = compose({ADD_VALUE: JevAnswer(id=ADD_VALUE, type="noul", value=1.0)},
                config=CascadeConfig())
    assert d.action == "silent"
    assert "incomplete" in d.reason


# -- decide -----------------------------------------------------------------
class _FakeClient:
    def __init__(self, answers):
        self._answers = answers
        self.calls = 0

    def ask(self, state, questions):
        self.calls += 1
        # state must be structured JSON, not a bare string
        assert isinstance(state, dict)
        return self._answers


class _BoomClient:
    def ask(self, state, questions):
        from luna_core.jev import JevError

        raise JevError("down")


def test_decide_wakes_on_high_confidence(budget):
    client = _FakeClient(_answers(message_fit=0.9))
    d = decide(client, candidate=_candidate(), ctx=_ctx(), recent=[], budget=budget, now=NOW)
    assert d.action == MESSAGE
    assert client.calls == 1


def test_decide_directed_wake(budget):
    d = decide(_FakeClient(_answers(addressed=0.9)), candidate=_candidate(), ctx=_ctx(), recent=[],
               budget=budget, now=NOW)
    assert d.action == MESSAGE
    assert d.directed is True


def test_decide_skips_jev_when_prefiltered(budget):
    client = _FakeClient(_answers(message_fit=0.9))
    d = decide(client, candidate=_candidate(is_bot=True), ctx=_ctx(), recent=[], budget=budget,
               now=NOW)
    assert d.action == "silent"
    assert client.calls == 0


def test_decide_fails_closed_on_jev_error(budget):
    d = decide(_BoomClient(), candidate=_candidate(), ctx=_ctx(), recent=[], budget=budget, now=NOW)
    assert d.action == "silent"
    assert "fail closed" in d.reason


def test_decide_has_no_code_cap_by_default(budget):
    """Default policy imposes no frequency cap — jev decides."""
    budget.record(MESSAGE, "-100", trigger_message_id="x", now=NOW - timedelta(minutes=1))
    d = decide(_FakeClient(_answers(message_fit=0.9)), candidate=_candidate(), ctx=_ctx(), recent=[], budget=budget,
               now=NOW)
    assert d.action == MESSAGE  # not suppressed by a cap


def test_decide_respects_a_configured_cap(tmp_path):
    from luna_core.wakes import WakePolicy

    conn = db.connect(tmp_path / "capped.db")
    db.init_db(conn)
    budget = WakeBudget(conn, WakePolicy(message_cooldown_minutes=360, message_max_per_day=2,
                                         message_max_per_week=6))
    budget.record(MESSAGE, "-100", trigger_message_id="x", now=NOW - timedelta(minutes=5))
    d = decide(_FakeClient(_answers(message_fit=0.9)), candidate=_candidate(), ctx=_ctx(), recent=[], budget=budget,
               now=NOW)
    assert d.action == "silent"
    assert "stage3" in d.reason
    conn.close()


def test_budget_woken_for_dedup(budget):
    assert budget.woken_for("m1") is False
    budget.record(MESSAGE, "-100", trigger_message_id="m1", now=NOW)
    assert budget.woken_for("m1") is True


def test_is_media_only_detects_placeholders():
    assert is_media_only("[video 'file.mp4' saved at: /home/x/cache/videos/file.mp4]")
    assert is_media_only("[sticker 'x.webp' saved at: /y]")
    assert is_media_only("[gif 'g.mp4' saved at: /y]")
    assert is_media_only("[image 'i.jpg' saved at: /y]")
    # Real text alongside a placeholder is not media-only.
    assert not is_media_only("[video 'x.mp4' saved at: /y]\nwhy is this so laggy")
    # Plain text is never media-only.
    assert not is_media_only("anyone know a good pizza place nearby?")


def test_media_only_never_reacts_but_can_still_reply():
    """A GIF/sticker gets no tap, but a directed question about it still gets an answer."""
    media = "[video 'file.mp4' saved at: /home/x/cache/videos/file.mp4]"
    reaction_shaped = _answers(add_value=0.5, open_q=0.2, topic_fit=0.6,
                               reaction_fit=0.95, reaction_emoji="🤣", reaction_fresh=0.9,
                               emoji_confidence=0.9)
    d = compose(reaction_shaped, config=CascadeConfig(), reactions_enabled=True,
                allowed_reactions=REACTIONS, candidate_text=media)
    assert d.action != REACTION


def test_low_emoji_confidence_does_not_starve_reactions():
    """jev's emoji_choice confidence has median ~0.49; a 0.50 gate silently rejected 51% of
    otherwise-firing reactions. The allow-list already constrains the emoji."""
    from luna_core.cascade import CascadeConfig as _C
    assert _C().reaction_min_emoji_confidence == 0.35
    d = compose(_answers(add_value=0.5, open_q=0.2, topic_fit=0.6,
                         reaction_fit=0.75, reaction_emoji="👍", emoji_confidence=0.42,
                         reaction_fresh=0.88),
                config=_C(), reactions_enabled=True, allowed_reactions=REACTIONS)
    assert d.action == REACTION
    assert d.emoji == "👍"


def test_reaction_sensitive_bar_separates_dark_humour_from_real_distress():
    """Live calibration: a dark joke scores ~0.13-0.20, real distress 0.66-0.86.

    The old `topic_is_sensitive` wording rated BOTH at 0.93-0.98, so the 0.20 bar blocked
    legitimate reactions to this room's unhinged jokes.
    """
    from luna_core.cascade import CascadeConfig as _C
    assert _C().reaction_max_sensitive == 0.40

    joke = _answers(add_value=0.6, open_q=0.46, topic_fit=0.7,
                    sensitive=0.13, reaction_fit=0.88, reaction_emoji="😭",
                    reaction_fresh=0.73, emoji_confidence=0.76)
    assert compose(joke, config=_C(), reactions_enabled=True, allowed_reactions=REACTIONS).action == REACTION

    crisis = _answers(add_value=0.6, open_q=0.46, topic_fit=0.7,
                      sensitive=0.79, reaction_fit=0.89, reaction_emoji="👍",
                      reaction_fresh=0.73, emoji_confidence=0.76)
    assert compose(crisis, config=_C(), reactions_enabled=True, allowed_reactions=REACTIONS).action == "silent"


def test_room_state_describes_the_register():
    """The room's culture is stated in the room block (config), not the persona blurb."""
    from luna_core.cascade import build_state
    state = build_state(_candidate(), [], config=CascadeConfig(),
                        room_register="people joke around constantly and talk in memes")
    register = state["room"]["register"].lower()
    assert "joke" in register and "meme" in register
    assert "people joke around constantly and talk in memes" not in state["luna"].lower()
