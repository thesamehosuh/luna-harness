"""Component tests for the luna-ambient cascade wiring (dry-run vs record, candidate selection)."""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "luna" / "plugins" / "luna-ambient"
sys.path.insert(0, str(REPO_ROOT / "luna" / "lib"))

from luna_core import db as luna_db  # noqa: E402
from luna_core.cascade import (  # noqa: E402
    ADD_VALUE, ADDRESSED_DIRECT, ADDRESSED_NAME, CONTRIBUTION, INTERRUPTION, MESSAGE_FIT,
    OPEN_Q, PRIVATE, REACTION_EMOJI, REACTION_FIT, REACTION_FRESH, REDUNDANT, REQUESTS_REACTION,
    SENSITIVE, TIMELINESS, TOPIC_FIT, VENTING,
)
from luna_core.jev import JevAnswer  # noqa: E402

CHAT = "-1000000000000"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _load_plugin():
    spec = importlib.util.spec_from_file_location("luna_ambient_plugin", PLUGIN_DIR / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_worker_startup_reads_settings_in_owning_profile(tmp_path, monkeypatch, caplog):
    from agent import secret_scope
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override

    (tmp_path / '.env').write_text('LUNA_AMBIENT_DRY_RUN=false\n')
    (tmp_path / 'config.yaml').write_text('luna: {}\n')
    monkeypatch.setattr(secret_scope, '_MULTIPLEX_ACTIVE', True)
    profile = set_hermes_home_override(tmp_path)
    secrets = secret_scope.set_secret_scope(None)
    mod = _load_plugin()
    seen = []
    monkeypatch.setattr(mod, '_loop', lambda ref: seen.append(mod._dry_run()))
    try:
        with caplog.at_level(logging.INFO):
            mod._ensure_thread(None)
        mod._THREAD.join(timeout=2)
        assert not mod._THREAD.is_alive()
        assert seen == [False]
        assert 'poller started (dry_run=False)' in caplog.text
        assert secret_scope.current_secret_scope() is None
    finally:
        secret_scope.reset_secret_scope(secrets)
        reset_hermes_home_override(profile)


class FakeJev:
    def __init__(self, add_value=0.95, reaction_fit=0.8, reaction_fresh=0.9,
                 addressed=0.05, requests_reaction=0.0, message_fit=0.0, open_q=0.8):
        self.calls = 0
        self._add_value = add_value
        self._reaction_fit = reaction_fit
        self._reaction_fresh = reaction_fresh
        self._addressed = addressed
        self._requests_reaction = requests_reaction
        self._message_fit = message_fit
        self._open_q = open_q

    def ask(self, state, questions):
        self.calls += 1
        vals = {
            ADD_VALUE: self._add_value, OPEN_Q: self._open_q, TOPIC_FIT: 0.9, REDUNDANT: 0.05,
            VENTING: 0.05, SENSITIVE: 0.05, PRIVATE: 0.05, MESSAGE_FIT: self._message_fit,
            ADDRESSED_NAME: self._addressed, ADDRESSED_DIRECT: self._addressed, INTERRUPTION: 0,
            TIMELINESS: 1, CONTRIBUTION: "fact",
            REACTION_EMOJI: "😭", REACTION_FIT: self._reaction_fit,
            REACTION_FRESH: self._reaction_fresh,
            REQUESTS_REACTION: self._requests_reaction,
        }
        from luna_core.cascade import build_questions
        specs = {q['id']: q for q in build_questions(["👍", "🤣", "😭"])}
        answers = {k: JevAnswer(id=k, type=specs[k]['type'], value=v) for k, v in vals.items()}
        answers[REACTION_EMOJI].confidence = 0.8
        return answers


def _iso(dt):
    return dt.isoformat()


def _seed(conn):
    rows = [
        ("l0", "luna", "Luna", "hey all", NOW - timedelta(minutes=12), 1, None),
        ("m1", "u1", "Alex", "anyone know a good pizza place nearby?", NOW - timedelta(minutes=10), 0, None),
        ("m2", "u2", "Babi", "the one by the station is decent", NOW - timedelta(minutes=6), 0, None),
        ("m3", "u3", "Dia", "we should go friday", NOW - timedelta(minutes=2), 0, None),
    ]
    for mid, uid, name, text, ts, is_bot, reply in rows:
        conn.execute(
            "INSERT INTO messages(message_id, chat_id, user_id, user_name, peer_id, content, "
            "timestamp, reply_to_message_id, is_bot, observed) VALUES (?,?,?,?,?,?,?,?,?,1)",
            (mid, CHAT, uid, name, "luna" if is_bot else None, text, _iso(ts), reply, is_bot),
        )
    conn.commit()


# A watermark just before m1, so the poller has a live message to evaluate (not a stale backlog).
INITIAL_WATERMARK = NOW - timedelta(minutes=11)


@pytest.fixture()
def ambient(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_INDEX_DB", str(tmp_path / "luna-state.db"))
    monkeypatch.setenv("LUNA_CHAT_ID", CHAT)
    monkeypatch.setenv("LUNA_AMBIENT_DRY_RUN", "true")
    monkeypatch.setenv("LUNA_AMBIENT_STALE_AFTER_MINUTES", "60")
    # Settle gating is exercised by its own tests; the rest of the suite assumes every
    # candidate is old enough to evaluate.
    monkeypatch.setenv("LUNA_AMBIENT_SETTLE_SECONDS", "0")
    # Explicitly enable the reaction tier (absent config means tier OFF — see
    # test_reaction_tier_is_off_when_unconfigured).
    monkeypatch.setenv("LUNA_AMBIENT_REACTIONS", "👍,🤣,😭")
    # Hermetic: never read the live $HERMES_HOME config.yaml (emoji policy etc.).
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "SOUL.md").write_text("# Luna\n\nA test companion.\n")
    # Cascade tests explicitly opt in; the product template now starts with Jev pending/off.
    (tmp_path / "config.yaml").write_text("luna:\n  setup:\n    jev: enabled\n  ambient:\n    enabled: true\n")
    from luna_core import text as text_mod

    text_mod._EMOJI_POLICY_CACHE = None
    mod = _load_plugin()
    conn = luna_db.connect(tmp_path / "luna-state.db")
    luna_db.init_db(conn)
    _seed(conn)
    luna_db.set_meta(conn, mod._watermark_key(CHAT), _iso(INITIAL_WATERMARK))
    yield mod, conn
    conn.close()


def test_candidate_is_newest_unevaluated(ambient):
    mod, conn = ambient
    cand = mod._candidate(conn, CHAT)
    assert cand is not None
    # Newest non-bot, non-triggered substantive message: a directed message is answered promptly.
    assert cand.message_id == "m3"


def test_candidate_logs_messages_filtered_before_jev(ambient, caplog):
    mod, conn = ambient
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, user_id, user_name, content, timestamp, is_bot, observed) "
        "VALUES (?,?,?,?,?,?,0,1)",
        ("m4", CHAT, "u4", "Alex", "ok", _iso(NOW - timedelta(minutes=1))),
    )
    conn.commit()
    caplog.set_level("INFO", logger="luna-ambient")

    assert mod._candidate(conn, CHAT).message_id == "m3"
    assert mod._candidate(conn, CHAT).message_id == "m3"
    assert "event=skip" in caplog.text
    assert "reason=not substantive" in caplog.text
    assert 'trig=m4 who="Alex"' in caplog.text
    assert 'text="ok"' not in caplog.text  # no message text in logs
    assert caplog.text.count("trig=m4 ") == 1


def test_candidate_logs_already_woken_and_reply_to_luna(ambient, caplog):
    mod, conn = ambient
    for message_id, user_id, user_name, text, timestamp, reply_to in [
        ("m4", "u4", "Alex", "a reply for Luna here", _iso(NOW - timedelta(minutes=1)), "l0"),
        ("m5", "u5", "Babi", "another complete message",
         _iso(NOW - timedelta(seconds=30)), None),
    ]:
        conn.execute(
            "INSERT INTO messages(message_id, chat_id, user_id, user_name, content, timestamp, "
            "reply_to_message_id, is_bot, observed) VALUES (?,?,?,?,?,?,?,0,1)",
            (message_id, CHAT, user_id, user_name, text, timestamp, reply_to),
        )
    conn.execute(
        "INSERT INTO wakes(kind, chat_id, trigger_message_id, detail, created_at) VALUES (?,?,?,?,?)",
        ("message", CHAT, "m5", "{}", _iso(NOW)),
    )
    conn.commit()
    caplog.set_level("INFO", logger="luna-ambient")

    assert mod._candidate(conn, CHAT).message_id == "m3"
    assert "reason=already woken" in caplog.text
    assert "reason=reply to companion" in caplog.text
    assert 'trig=m5 who="Babi"' in caplog.text
    assert 'trig=m4 who="Alex"' in caplog.text


def test_triggered_message_is_logged_as_handled_reactively(ambient, caplog):
    mod, conn = ambient
    luna_db.mark_triggered(conn, "m3")
    caplog.set_level("INFO", logger="luna-ambient")

    assert mod._log_triggered_messages(conn, CHAT, after=_iso(INITIAL_WATERMARK)) == 1
    assert "event=skip" in caplog.text
    assert "reason=handled reactively" in caplog.text
    assert 'trig=m3 who="Dia"' in caplog.text


def test_watermark_prevents_reevaluation(ambient):
    mod, conn = ambient
    mod.evaluate(conn, CHAT, now=NOW, dry_run=True, client=FakeJev(message_fit=0.9))
    # The newest message was evaluated, so nothing newer remains.
    assert luna_db.get_meta(conn, mod._watermark_key(CHAT)) == _iso(NOW - timedelta(minutes=2))
    assert mod._candidate(conn, CHAT) is None


def test_evaluate_logs_older_messages_superseded_without_jev(ambient, caplog):
    mod, conn = ambient
    caplog.set_level("INFO", logger="luna-ambient")

    mod.evaluate(conn, CHAT, now=NOW, dry_run=True, client=FakeJev(message_fit=0.9))

    assert "reason=superseded by newer message" in caplog.text
    assert 'trig=m1 who="Alex"' in caplog.text
    assert 'trig=m2 who="Babi"' in caplog.text
    assert "trig=m3 " not in caplog.text


def test_watermark_not_advanced_on_jev_error(ambient):
    mod, conn = ambient

    class Boom:
        def ask(self, state, questions):
            from luna_core.jev import JevError

            raise JevError("HTTP 429: rate limited")

    decision = mod.evaluate(conn, CHAT, now=NOW, dry_run=True, client=Boom())
    # The watermark is left where it was (retried later), not advanced past the failed message.
    assert luna_db.get_meta(conn, mod._watermark_key(CHAT)) == _iso(INITIAL_WATERMARK)
    assert decision.target_message_id == "m3"
    assert decision.target_user == "Dia"
    assert decision.target_text == "we should go friday"


def test_regex_fallback_wakes_on_mention_when_jev_is_down(ambient, monkeypatch):
    """jev error -> the configured mention regex is the only thing that still wakes her."""
    mod, conn = ambient
    monkeypatch.setenv("LUNA_AMBIENT_MENTION_FALLBACK", r"(?i)\bluna\b")
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, user_id, user_name, peer_id, content, "
        "timestamp, is_bot, observed) VALUES (?,?,?,?,?,?,?,?,1)",
        ("m4", CHAT, "u4", "Rayden", None, "yo luna what do you think", _iso(NOW), 0),
    )
    conn.commit()

    class Boom:
        def ask(self, state, questions):
            from luna_core.jev import JevError

            raise JevError("HTTP 429: rate limited")

    decision = mod.evaluate(conn, CHAT, now=NOW, dry_run=True, client=Boom())
    assert decision.action == "message"
    assert decision.directed is True
    assert decision.target_message_id == "m4"
    assert "fallback" in decision.reason


def test_regex_fallback_silent_without_pattern(ambient, tmp_path, monkeypatch):
    """No patterns configured = no fallback: jev down means silence (the default)."""
    mod, conn = ambient
    monkeypatch.delenv("LUNA_AMBIENT_MENTION_FALLBACK", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))  # no config.yaml -> no patterns
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, user_id, user_name, peer_id, content, "
        "timestamp, is_bot, observed) VALUES (?,?,?,?,?,?,?,?,1)",
        ("m4", CHAT, "u4", "Rayden", None, "yo luna what do you think", _iso(NOW), 0),
    )
    conn.commit()

    class Boom:
        def ask(self, state, questions):
            from luna_core.jev import JevError

            raise JevError("HTTP 429: rate limited")

    decision = mod.evaluate(conn, CHAT, now=NOW, dry_run=True, client=Boom())
    assert decision.action == "silent"


def test_evaluate_wakes_on_high_confidence(ambient):
    mod, conn = ambient
    jev = FakeJev(message_fit=0.9)
    decision = mod.evaluate(conn, CHAT, now=NOW, dry_run=True, client=jev)
    assert decision.action == "message"
    assert jev.calls == 1
    # dry-run must not record a wake
    assert conn.execute("SELECT COUNT(*) FROM wakes").fetchone()[0] == 0


def test_evaluate_does_not_record_before_delivery(ambient):
    """A wake is recorded only after delivery, so a failed send is never silently skipped."""
    mod, conn = ambient
    decision = mod.evaluate(conn, CHAT, now=NOW, dry_run=False, client=FakeJev(message_fit=0.9))
    assert decision.action == "message"
    assert conn.execute("SELECT COUNT(*) FROM wakes").fetchone()[0] == 0
    mod._record_wake(conn, decision, now=NOW)  # caller records after confirmed delivery
    assert conn.execute("SELECT COUNT(*) FROM wakes").fetchone()[0] == 1


def test_generated_wake_reply_is_logged_for_the_verdict_stream(ambient, monkeypatch, caplog):
    mod, conn = ambient
    from luna_core.cascade import Decision

    calls = []

    class FakeCtx:
        def inject_message(self, content, *, session_key, reply_to_message_id, luna_delivery=None):
            calls.append((content, session_key, reply_to_message_id))
            self.receipt = luna_delivery
            return True

    decision = Decision(
        action="message",
        chat_id=CHAT,
        target_message_id="m3",
        target_user="Dia",
        target_text="we should go friday",
    )
    brief = "A private ambient wake brief"
    monkeypatch.setattr(mod, "_CTX", FakeCtx(), raising=False)
    caplog.set_level("INFO", logger="luna-ambient")

    monkeypatch.setattr(mod, "_still_relevant", lambda decision: True)
    assert mod._inject(brief, CHAT, decision) is True
    mod._on_post_llm_call(
        user_message="an unrelated turn",
        assistant_response="This must not be attributed to Luna's wake.",
    )
    mod._on_post_llm_call(
        user_message=brief,
        assistant_response="Friday works. I am in.",
    )

    assert "event=said" not in caplog.text
    assert conn.execute("SELECT COUNT(*) FROM wakes").fetchone()[0] == 0
    mod._CTX.receipt["complete"]("delivered", "Friday works. I am in.", "delivered-1")
    assert calls == [(brief, mod._room_session_key(CHAT), "m3")]
    assert "event=said" in caplog.text
    assert "trig=m3" in caplog.text
    assert 'reply="' not in caplog.text  # no reply text in logs
    assert "must not be attributed" not in caplog.text


def test_failed_delivery_leaves_message_retryable(ambient):
    """poll_once rolls the watermark back on failure; with no wake row the message is re-offered."""
    mod, conn = ambient
    wm_before = luna_db.get_meta(conn, mod._watermark_key(CHAT))
    decision = mod.evaluate(conn, CHAT, now=NOW, dry_run=False, client=FakeJev(message_fit=0.9))
    assert decision.should_wake
    # Delivery failed: no _record_wake, and poll_once restores the watermark.
    luna_db.set_meta(conn, mod._watermark_key(CHAT), wm_before)
    cand = mod._candidate(conn, CHAT)
    assert cand is not None and cand.message_id == decision.target_message_id


def test_failed_delivery_retries_are_bounded(ambient, monkeypatch, caplog):
    """An unrecoverable send must not re-spend a jev batch on every poll forever."""
    mod, conn = ambient
    monkeypatch.setattr(mod, "_still_relevant", lambda decision: True)
    monkeypatch.setattr(mod, "_inject", lambda *a, **k: False)
    monkeypatch.setattr(mod, "_jev_client", lambda *a, **k: FakeJev(message_fit=0.9))
    # The fixture clock is January; poll_once uses the wall clock and would fast-forward past
    # the seeded backlog. Freeze the staleness sweep so the candidate stays in range.
    monkeypatch.setattr(mod, "_fast_forward_if_stale", lambda *a, **k: None)
    monkeypatch.setenv("LUNA_AMBIENT_DRY_RUN", "false")
    caplog.set_level("WARNING", logger="luna-ambient")
    for _ in range(mod._DELIVERY_ATTEMPTS_MAX + 2):
        mod.poll_once(ctx=None)
        luna_db.set_meta(conn, mod._watermark_key(CHAT), _iso(INITIAL_WATERMARK))
    assert "giving up" in caplog.text


def test_evaluate_stays_silent_on_low_value(ambient):
    mod, conn = ambient
    decision = mod.evaluate(conn, CHAT, now=NOW, dry_run=True,
                            client=FakeJev(add_value=0.2, reaction_fit=0.1))
    assert decision.action == "silent"


def test_evaluate_reaction_fires_on_fit(ambient):
    mod, conn = ambient
    # No open question -> a tap is the right response.
    decision = mod.evaluate(conn, CHAT, now=NOW, dry_run=True,
                            client=FakeJev(add_value=0.5, reaction_fit=0.9, open_q=0.1))
    assert decision.action == "reaction"


def test_reaction_tier_is_off_when_unconfigured(tmp_path, monkeypatch):
    """Absent ``luna.ambient.reactions.allowed`` = tier OFF (plan D19), never a built-in palette."""
    monkeypatch.delenv("LUNA_AMBIENT_REACTIONS", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))  # no config.yaml -> no allow-list
    monkeypatch.setenv("LUNA_INDEX_DB", str(tmp_path / "luna-state.db"))
    monkeypatch.setenv("LUNA_CHAT_ID", CHAT)
    mod = _load_plugin()
    assert mod._allowed_reactions() == []


def test_reaction_yields_to_a_genuine_open_question(ambient):
    """A tap must not swallow a real question Luna could answer; she owes words."""
    mod, conn = ambient
    decision = mod.evaluate(conn, CHAT, now=NOW, dry_run=True,
                            client=FakeJev(add_value=0.5, reaction_fit=0.9, open_q=0.9,
                                           message_fit=0.3))
    # Value is below the message bar, so she stays quiet rather than tapping a question.
    assert decision.action == "silent"
    assert decision.emoji is None


def _real_loop():
    """A genuine event loop in a background thread, so run_coroutine_threadsafe really dispatches."""
    import asyncio as _asyncio
    import threading as _threading

    loop = _asyncio.new_event_loop()
    ready = _threading.Event()

    def _run():
        _asyncio.set_event_loop(loop)
        loop.call_soon(ready.set)
        loop.run_forever()

    t = _threading.Thread(target=_run, daemon=True)
    t.start()
    ready.wait(5)
    return loop, t


def test_reaction_verdict_reaches_telegram_send_reaction(ambient, monkeypatch):
    """A REACTION verdict must call platform_actions.add_reaction with the right routing.

    Guards the whole chain: jev verdict -> _send_reaction -> PlatformActions.add_reaction ->
    adapter.set_message_reaction(chat, message_id, emoji).
    """
    mod, conn = ambient
    calls = []

    class FakeActions:
        async def add_reaction(self, platform, chat_id, message_id, emoji):
            calls.append((platform, chat_id, message_id, emoji))
            return {"ok": True, "action": "add_reaction"}

    class FakeCtx:
        platform_actions = FakeActions()

    loop, t = _real_loop()
    try:
        monkeypatch.setattr(mod, "_CTX", FakeCtx(), raising=False)
        monkeypatch.setattr(mod, "_gateway_loop", lambda: loop, raising=False)

        from luna_core.cascade import REACTION, Decision

        decision = Decision(action=REACTION, chat_id=CHAT, target_message_id="m3", emoji="🤣")
        monkeypatch.setattr(mod, "_still_relevant", lambda decision: True)
        assert mod._send_reaction(decision) is True
        assert calls == [("telegram", CHAT, "m3", "🤣")]
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=5)
        loop.close()


def test_reaction_send_failure_is_reported(ambient, monkeypatch):
    """A failed Telegram reaction must return False so the wake is retried, not silently dropped."""
    mod, conn = ambient

    class FakeActions:
        async def add_reaction(self, platform, chat_id, message_id, emoji):
            return {"ok": False, "error": "REACTION_INVALID"}

    class FakeCtx:
        platform_actions = FakeActions()

    loop, t = _real_loop()
    try:
        monkeypatch.setattr(mod, "_CTX", FakeCtx(), raising=False)
        monkeypatch.setattr(mod, "_gateway_loop", lambda: loop, raising=False)

        from luna_core.cascade import REACTION, Decision

        decision = Decision(action=REACTION, chat_id=CHAT, target_message_id="m3", emoji="👍")
        assert mod._send_reaction(decision) is False
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=5)
        loop.close()


def _fresh_index(tmp_path, monkeypatch, *, stale="60"):
    monkeypatch.setenv("LUNA_INDEX_DB", str(tmp_path / "luna-state.db"))
    monkeypatch.setenv("LUNA_CHAT_ID", CHAT)
    monkeypatch.setenv("LUNA_AMBIENT_STALE_AFTER_MINUTES", stale)
    monkeypatch.setenv("LUNA_AMBIENT_SETTLE_SECONDS", "0")
    mod = _load_plugin()
    conn = luna_db.connect(tmp_path / "luna-state.db")
    luna_db.init_db(conn)
    _seed(conn)
    return mod, conn


def test_init_watermark_starts_at_newest(tmp_path, monkeypatch):
    """A fresh index must not grind through history one message per poll."""
    mod, conn = _fresh_index(tmp_path, monkeypatch)
    try:
        mod._init_watermark(conn, CHAT, now=NOW)
        assert luna_db.get_meta(conn, mod._watermark_key(CHAT)) == _iso(NOW - timedelta(minutes=2))
    finally:
        conn.close()


def test_fast_forward_skips_stale_backlog(tmp_path, monkeypatch, caplog):
    mod, conn = _fresh_index(tmp_path, monkeypatch, stale="5")
    try:
        luna_db.set_meta(conn, mod._watermark_key(CHAT), _iso(NOW - timedelta(hours=2)))
        caplog.set_level("INFO", logger="luna-ambient")
        mod._fast_forward_if_stale(conn, CHAT, now=NOW)
        assert luna_db.get_meta(conn, mod._watermark_key(CHAT)) == _iso(NOW - timedelta(minutes=2))
        assert "reason=stale backlog" in caplog.text
        assert 'trig=m1 who="Alex"' in caplog.text
        assert 'trig=m2 who="Babi"' in caplog.text
        assert 'trig=m3 who="Dia"' in caplog.text
    finally:
        conn.close()


def test_402_payment_wall_pauses_without_retry_after(ambient, monkeypatch):
    """HTTP 402 sends no retry-after: without a default cooldown every poll re-asks the same
    message forever (the 402 storm). It must pause for the long wall cooldown."""
    mod, conn = ambient
    monkeypatch.setattr(mod, "_JEV_PAUSE_UNTIL", 0.0, raising=False)
    monkeypatch.setattr(mod, "_JEV_PAUSE_REASON", "", raising=False)

    class Broke:
        def ask(self, state, questions):
            from luna_core.jev import JevError

            raise JevError("HTTP 402: payment required")

    decision = mod.evaluate(conn, CHAT, now=NOW, dry_run=True, client=Broke())
    assert decision.action == "silent"
    assert mod._jev_paused() is True
    remaining = mod._JEV_PAUSE_UNTIL - __import__("time").monotonic()
    assert remaining > 300  # the long wall cooldown, not the short error backoff
    assert luna_db.get_meta(conn, mod._watermark_key(CHAT)) == _iso(INITIAL_WATERMARK)


def test_other_jev_errors_get_a_short_backoff(ambient, monkeypatch):
    """A persistent non-402 failure must not re-spend a request batch every poll either."""
    mod, conn = ambient
    monkeypatch.setattr(mod, "_JEV_PAUSE_UNTIL", 0.0, raising=False)
    monkeypatch.setattr(mod, "_JEV_PAUSE_REASON", "", raising=False)

    class Broken:
        def ask(self, state, questions):
            from luna_core.jev import JevError

            raise JevError("HTTP 503: upstream exploded")

    mod.evaluate(conn, CHAT, now=NOW, dry_run=True, client=Broken())
    assert mod._jev_paused() is True
    remaining = mod._JEV_PAUSE_UNTIL - __import__("time").monotonic()
    assert 0 < remaining <= 120


def test_jev_rate_limit_pauses_then_resumes(ambient, monkeypatch, caplog):
    """A 429 with a long retry-after must stop the request storm, then resume on its own."""
    mod, conn = ambient
    monkeypatch.setattr(mod, "_JEV_PAUSE_UNTIL", 0.0, raising=False)
    monkeypatch.setattr(mod, "_JEV_PAUSE_REASON", "", raising=False)

    class Throttled:
        def ask(self, state, questions):
            from luna_core.jev import JevError

            raise JevError("HTTP 429: FreeUsageLimitError (retry-after 47728s)")

    decision = mod.evaluate(conn, CHAT, now=NOW, dry_run=True, client=Throttled())
    assert decision.action == "silent"
    assert mod._jev_paused() is True
    # The evaluation watermark must not move, so nothing is skipped once jev returns.
    assert luna_db.get_meta(conn, mod._watermark_key(CHAT)) == _iso(INITIAL_WATERMARK)

    # A paused poller issues no jev request at all.
    class Explode:
        def ask(self, state, questions):
            raise AssertionError("jev must not be called while paused")

    mod._JEV_PAUSE_UNTIL = mod.time.monotonic() + 5
    caplog.set_level("INFO", logger="luna-ambient")
    mod.poll_once(ctx=None)
    assert "reason=jev paused" in caplog.text
    assert 'trig=m1 who="Alex"' in caplog.text
    assert 'trig=m3 who="Dia"' in caplog.text


def test_pause_is_capped_so_luna_cannot_be_disabled_forever(ambient, monkeypatch):
    mod, conn = ambient
    monkeypatch.setattr(mod, "_JEV_PAUSE_UNTIL", 0.0, raising=False)
    monkeypatch.setattr(mod, "_JEV_PAUSE_REASON", "", raising=False)
    mod._pause_jev(999999.0, "jev error")
    remaining = mod._JEV_PAUSE_UNTIL - mod.time.monotonic()
    assert remaining <= mod.JEV_PAUSE_MAX_SECONDS + 1
    # Expiring the pause clears it and evaluation resumes.
    mod._JEV_PAUSE_UNTIL = mod.time.monotonic() - 1
    assert mod._jev_paused() is False


def test_jev_key_reflects_the_env_file_not_a_stale_process_copy(tmp_path, monkeypatch):
    """Rotating the key in .env must not require a gateway restart."""
    mod = _load_plugin()
    env_file = tmp_path / ".env"
    env_file.write_text("OPENCODE_ZEN_API_KEY=sk-rotated\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # The real ~/.luna/.env fallback must not leak into the test.
    monkeypatch.setattr(mod.Path, "home", classmethod(lambda cls: tmp_path / "nohome"))
    # Simulate a gateway that captured the key at start-up.
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "sk-stale")
    assert mod._jev_api_key("OPENCODE_ZEN_API_KEY") == "sk-rotated"

    # With no file entry, an exported variable still works.
    env_file.write_text("OTHER=1\n", encoding="utf-8")
    assert mod._jev_api_key("OPENCODE_ZEN_API_KEY") == "sk-stale"

    # And an explicit env-only setup keeps working with no .env at all.
    env_file.unlink()
    assert mod._jev_api_key("OPENCODE_ZEN_API_KEY") == "sk-stale"


def test_cascade_thresholds_are_read_from_config(tmp_path, monkeypatch):
    """Every CascadeConfig field is wired: a config value must reach the cascade (these gates
    used to be dead keys — editing them did nothing)."""
    (tmp_path / "config.yaml").write_text(
        "luna:\n"
        "  ambient:\n"
        "    thresholds:\n"
        "      safety_max_sensitive: 0.11\n"
        "      message_max_venting: 0.22\n"
        "      min_candidate_chars: 17\n"
        "      w_add_value: 0.5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_plugin()
    cfg = mod._cascade_config()
    assert cfg.safety_max_sensitive == 0.11
    assert cfg.message_max_venting == 0.22
    assert cfg.min_candidate_chars == 17
    assert cfg.w_add_value == 0.5
    # Absent keys fall back to the CascadeConfig defaults (the single source of truth).
    assert cfg.message_min_fit == mod.CascadeConfig().message_min_fit
    # Env overrides config.
    monkeypatch.setenv("LUNA_AMBIENT_SAFETY_MAX_SENSITIVE", "0.05")
    assert mod._cascade_config().safety_max_sensitive == 0.05
    # The old config key name still works.
    (tmp_path / "config.yaml").write_text(
        "luna:\n  ambient:\n    thresholds:\n      message_max_emotional: 0.33\n",
        encoding="utf-8",
    )
    assert mod._cascade_config().message_max_venting == 0.33


def test_reaction_activity_summary_anchors_the_cadence(ambient, monkeypatch):
    """jev cannot judge freshness without a cadence to compare against; code supplies it."""
    mod, conn = ambient
    from luna_core.wakes import REACTION
    now = NOW
    conn.execute(
        "INSERT INTO wakes(chat_id, kind, trigger_message_id, detail, created_at) VALUES (?,?,?,?,?)",
        (CHAT, REACTION, "old", "{}", (now - timedelta(minutes=40)).isoformat()),
    )
    conn.commit()

    monkeypatch.setattr(mod, "_wake_policy", lambda: mod.WakePolicy(reaction_cooldown_minutes=15))
    passed = mod._luna_recent_activity(conn, CHAT, now=now)
    assert "every 15 minutes" in passed
    assert "window has already passed" in passed

    # Inside the window the summary must read as repetitive.
    conn.execute("DELETE FROM wakes")
    conn.execute(
        "INSERT INTO wakes(chat_id, kind, trigger_message_id, detail, created_at) VALUES (?,?,?,?,?)",
        (CHAT, REACTION, "just", "{}", (now - timedelta(minutes=2)).isoformat()),
    )
    conn.commit()
    blocked = mod._luna_recent_activity(conn, CHAT, now=now)
    assert "would feel repetitive" in blocked
    assert "window has already passed" not in blocked

    # With no cooldown configured, no cadence claim is made at all.
    monkeypatch.setattr(mod, "_wake_policy", lambda: mod.WakePolicy(reaction_cooldown_minutes=0))
    plain = mod._luna_recent_activity(conn, CHAT, now=now)
    assert "every 0 minutes" not in plain


def test_directed_brief_leads_with_the_message_being_replied_to(ambient):
    """Replies must be about the target, not whatever else was in the room window."""
    mod, conn = ambient
    from luna_core.cascade import Decision

    decision = Decision(action="message", directed=True, chat_id=CHAT, target_message_id="m3")
    brief = mod._wake_brief(conn, CHAT, decision)

    # The target is named explicitly and appears before the background.
    target_label = "The message you are replying to:"
    background_label = "Room background (context only, do not reply to these):"
    assert target_label in brief
    assert brief.index(target_label) < brief.index(background_label)
    # The actual target text is present in that section.
    head = brief.split(target_label)[1].split(background_label)[0]
    assert "we should go friday" in head
    # Background is explicitly fenced off, and the instruction is singular in scope.
    assert "do not reply to these" in brief
    assert "and nothing else" in brief
    # She must never post that she has nothing to add.
    assert "return exactly NO_REPLY" in brief


def test_directed_brief_omits_background_when_target_is_the_only_message(ambient):
    mod, conn = ambient
    from luna_core.cascade import Decision

    conn.execute("DELETE FROM messages WHERE message_id != 'm3'")
    conn.commit()
    brief = mod._wake_brief(conn, CHAT,
                            Decision(action="message", directed=True, chat_id=CHAT,
                                      target_message_id="m3"))
    assert "we should go friday" in brief
    assert "Room background (context only" not in brief


def test_ambient_brief_keeps_room_context(ambient):
    """The non-directed path still gets room context; only the directed path is restructured."""
    mod, conn = ambient
    from luna_core.cascade import Decision

    brief = mod._wake_brief(conn, CHAT,
                            Decision(action="message", directed=False, chat_id=CHAT,
                                      target_message_id="m3", contribution_type="humor"))
    assert "you could join" in brief
    assert "Room context" in brief
    assert "The message you are replying to:" not in brief


def test_dashboard_authored_wake_prompts_reach_briefs(ambient, monkeypatch):
    mod, conn = ambient
    from luna_cli.behaviour import write_behaviour
    from luna_core.cascade import Decision
    # The dashboard transaction and runtime use the same isolated profile.
    from luna_core.runtime import home
    monkeypatch.setenv("LUNA_HOME", str(home()))
    result = write_behaviour({"wake_prompts": {"directed": "Answer with warmth.", "message": "Offer {contribution_type}; keep {literal} intact."}})
    assert result["results"]["wake_prompts"]["ok"]
    directed = mod._wake_brief(conn, CHAT, Decision(action="message", directed=True, target_message_id="m3"))
    assert directed.startswith("Answer with warmth.")
    assert "The message you are replying to:" in directed
    assert "Room background (context only, do not reply to these):" in directed
    spontaneous = mod._wake_brief(conn, CHAT, Decision(action="message", target_message_id="m3", contribution_type="humor"))
    assert spontaneous.startswith("Offer humor; keep {literal} intact.")


def test_outage_fallback_does_not_bypass_custom_text_conditions(ambient, monkeypatch):
    mod, conn = ambient
    previous = mod._cfg
    monkeypatch.setattr(mod, "_cfg", lambda key, default=None: {"rules": [{"id": "music", "name": "Music", "instructions": "Music?", "action": "message"}]} if key == "ambient.decision" else previous(key, default))
    monkeypatch.setattr(mod, "_mention_fallback_patterns", lambda: pytest.fail("Must not fall back without judging the condition"))
    assert mod._regex_fallback_decision(conn, CHAT, now=NOW) is None


def test_settle_gate_defers_a_brand_new_message(ambient, monkeypatch):
    """A message that just arrived is not worth a jev call yet, and must not be lost."""
    mod, conn = ambient
    monkeypatch.setenv("LUNA_AMBIENT_SETTLE_SECONDS", "10")
    # NOW is the fixture's clock; the newest message is 2 minutes old -> older than the window.
    # Re-evaluate "now" as 1 second after m3 arrived to make it brand new.
    decision = mod.evaluate(conn, CHAT, now=NOW - timedelta(minutes=2, seconds=-1),
                            dry_run=True, client=FakeJev(message_fit=0.9))
    assert decision.stage == "scan"
    assert "settling" in decision.reason
    assert decision.target_message_id == "m3"
    assert decision.target_user == "Dia"
    assert decision.target_text == "we should go friday"
    assert decision.scores["settle_wait_seconds"] > 0
    # The watermark must not move, or the message would be skipped forever.
    assert luna_db.get_meta(conn, mod._watermark_key(CHAT)) == _iso(INITIAL_WATERMARK)


def test_settle_gate_is_included_in_the_verdict_stream(ambient, monkeypatch, caplog):
    mod, conn = ambient
    from luna_core.cascade import Decision

    decision = Decision(
        action="silent",
        reason="candidate still settling",
        stage="scan",
        chat_id=CHAT,
        target_message_id="m3",
        target_user="Dia",
        target_text="we should go friday",
        scores={"settle_wait_seconds": 4.0},
    )
    monkeypatch.setattr(mod, "evaluate", lambda *args, **kwargs: decision)
    caplog.set_level("INFO", logger="luna-ambient")

    mod.poll_once()
    mod.poll_once()

    assert "event=settle" in caplog.text
    assert caplog.text.count("trig=m3 ") == 1
    assert "wait=4.0s" in caplog.text
    assert 'trig=m3 who="Dia"' in caplog.text


def test_name_prefilter_replays_configured_companion_names(ambient, tmp_path):
    mod, conn = ambient
    fixture = json.loads((REPO_ROOT / "luna/tests/fixtures/wakes/companion_names.json").read_text())
    config = {"luna": {"setup": {"jev": "enabled"},
                       "ambient": {"enabled": True, "thresholds": {"min_candidate_chars": 15}},
                       "character": {"name": fixture["name"], "aliases": fixture["aliases"]}}}
    (tmp_path / "config.yaml").write_text(json.dumps(config))
    for case in fixture["cases"]:
        conn.execute("UPDATE messages SET content=? WHERE message_id='m3'", (case["text"],))
        conn.commit()
        selected = mod._candidate(conn, CHAT)
        assert (selected is not None and selected.message_id == "m3") == case["selected"], case["text"]

    # With normal substance thresholds, unrelated short messages can still be
    # candidates, but only this character's names bypass the collection delay.
    config["luna"]["ambient"]["thresholds"]["min_candidate_chars"] = 3
    config["luna"]["ambient"]["settle_seconds"] = 600
    (tmp_path / "config.yaml").write_text(json.dumps(config))
    from unittest.mock import patch
    with patch.dict("os.environ", {"LUNA_AMBIENT_SETTLE_SECONDS": "600"}):
        for case in fixture["cases"]:
            conn.execute("UPDATE messages SET content=? WHERE message_id='m3'", (case["text"],))
            conn.commit()
            luna_db.set_meta(conn, mod._watermark_key(CHAT), _iso(INITIAL_WATERMARK))
            client = FakeJev(addressed=0.95, message_fit=0.9)
            mod.evaluate(conn, CHAT, now=NOW - timedelta(minutes=2, seconds=-1),
                         dry_run=True, client=client)
            assert bool(client.calls) == case["selected"], case["text"]


def test_settle_gate_never_delays_a_message_naming_luna(ambient, monkeypatch):
    """A message addressed to her by name is judged immediately, however fresh."""
    mod, conn = ambient
    monkeypatch.setenv("LUNA_AMBIENT_SETTLE_SECONDS", "600")
    fresh_now = NOW - timedelta(minutes=2, seconds=-1)
    conn.execute("UPDATE messages SET content='luna are you alive?' WHERE message_id='m3'")
    conn.commit()
    decision = mod.evaluate(conn, CHAT, now=fresh_now, dry_run=True,
                            client=FakeJev(addressed=0.95, message_fit=0.9))
    assert decision.stage != "scan"
    assert decision.directed is True


def test_wake_reply_is_group_shaped(ambient):
    """Self-wake replies bypass pre_gateway_dispatch — the group hard limits must still apply."""
    mod, conn = ambient
    from luna_core.cascade import Decision

    brief = "[Someone in the group is talking to you. Reply to the message below and nothing else.]"
    mod._remember_reply(brief, Decision(action="message", chat_id=CHAT,
                                        target_message_id="m3"), CHAT)
    mod._on_pre_llm_call(user_message=brief, session_id="wake-s1")

    draft = "**one** 🔥\ntwo\nthree\nfour\nfive"
    shaped = mod._on_transform_llm_output(response_text=draft, session_id="wake-s1")
    assert shaped is not None
    assert "🔥" not in shaped and "*" not in shaped
    assert len(shaped.splitlines()) <= 4
    # Every output on a marked session is shaped — a one-shot pop let the second output of the
    # same turn ship unshaped (streaming/retry paths).
    shaped2 = mod._on_transform_llm_output(response_text="**still** 🔥", session_id="wake-s1")
    assert shaped2 == "still"


def test_unmarked_sessions_are_not_shaped(ambient):
    mod, conn = ambient
    assert mod._on_transform_llm_output(response_text="**hi** 🔥", session_id="dm") is None


def test_wake_reply_is_recorded_in_room_log(ambient, monkeypatch):
    """The room log must contain Luna's own wake replies (chains + wake-frequency gates need them)."""
    mod, conn = ambient
    from luna_core.cascade import Decision

    class FakeCtx:
        def inject_message(self, content, *, session_key, reply_to_message_id, luna_delivery=None):
            self.receipt = luna_delivery
            return True

    brief = "A private ambient wake brief"
    monkeypatch.setattr(mod, "_CTX", FakeCtx(), raising=False)
    monkeypatch.setattr(mod, "_still_relevant", lambda decision: True)
    assert mod._inject(brief, CHAT, Decision(action="message", chat_id=CHAT,
                                             target_message_id="m3")) is True
    mod._on_post_llm_call(user_message=brief, assistant_response="Friday works. I am in.",
                          session_id="wake-s1", turn_id="t9")
    assert conn.execute("SELECT * FROM messages WHERE message_id = 'luna:wake-s1:t9'").fetchone() is None
    mod._CTX.receipt["complete"]("delivered", "Friday works. I am in.", "wake-delivered-t9")
    row = conn.execute("SELECT * FROM messages WHERE message_id = 'wake-delivered-t9'").fetchone()
    assert row is not None
    assert row["is_bot"] == 1 and row["peer_id"] == "luna"
    assert row["content"] == "Friday works. I am in."


# ---------------------------------------------------------------------------
# Privacy: the verdict log is an operator artifact, not a transcript archive
# ---------------------------------------------------------------------------


def test_verdict_log_never_contains_message_text(caplog, ambient):
    """Every ambient log line carries ids/reasons/weights, never the message or reply text.

    PRODUCT_PLAN P5: the wake story is tuned from the weights, so the log does not need the room's
    words. Guards the NOT-SENT path, which used to write every unjudged message verbatim.
    """
    mod, _conn = ambient
    secret = "my bank password is hunter2"
    with caplog.at_level(logging.INFO):
        mod._log_not_sent("m-privacy", "not substantive", user="Alex", text=secret)
    assert "m-privacy" in caplog.text
    assert "not substantive" in caplog.text
    assert secret not in caplog.text
