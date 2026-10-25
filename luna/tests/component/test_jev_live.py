"""Live jev test — opt-in.

Skipped unless a real OpenCode **Zen** key is available (env, `~/.luna/.env`, or `~/.hermes/.env`).
OpenCode **Go** keys do NOT work here: Go does not serve `/systemone`.

Run:
    .venv/bin/python -m pytest -q luna/tests/component/test_jev_live.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "luna" / "lib"))

from luna_core.env import load_luna_env  # noqa: E402
from luna_core.cascade import Candidate, CascadeConfig, build_questions, build_state, compose  # noqa: E402
from luna_core.jev import JevClient, JevError, noul  # noqa: E402

load_luna_env()

_KEY = os.getenv("OPENCODE_ZEN_API_KEY", "").strip()
_PLACEHOLDER = not _KEY or _KEY.startswith("PASTE_")

def _is_transient_service_error(exc: Exception) -> bool:
    """Live service-side flakes (5xx/upstream parse errors) are not regressions of our code."""
    text = str(exc)
    return any(tok in text for tok in ("server_error", "was not valid JSON", "502", "503", "504"))


pytestmark = pytest.mark.skipif(
    _PLACEHOLDER,
    reason="no OpenCode Zen key set (put OPENCODE_ZEN_API_KEY in ~/.luna/.env)",
)


def test_live_jev_returns_a_decision():
    client = JevClient(
        base_url=os.getenv("LUNA_JEV_BASE_URL", "https://opencode.ai/zen/v1"),
        model=os.getenv("LUNA_JEV_MODEL", "jev-1.13-free"),
        api_key=_KEY,
    )
    try:
        answers = client.ask(
            "A friend asks: does anyone know a good pizza place near the station?",
            [noul("is_open_question", "Is there an open question someone could answer?",
                  {"yes": "open question", "no": "no question"})],
        )
    except JevError as exc:
        if "429" in str(exc) or "FreeUsageLimit" in str(exc):
            pytest.skip(f"jev free-tier rate limit reached: {exc}")
        if "transport error" in str(exc):
            pytest.skip(f"jev endpoint unreachable (network/TLS): {exc}")
        if _is_transient_service_error(exc):
            pytest.skip(f"jev service transiently unhealthy: {exc}")
        pytest.fail(f"live jev call failed: {exc}")

    assert "is_open_question" in answers
    p = answers["is_open_question"].as_probability()
    assert 0.0 <= p <= 1.0


def test_live_cascade_question_batch_parses():
    """The full 12-question self-wake batch must return parseable answers from the real model."""
    client = JevClient(
        base_url=os.getenv("LUNA_JEV_BASE_URL", "https://opencode.ai/zen/v1"),
        model=os.getenv("LUNA_JEV_MODEL", "jev-1.13-free"),
        api_key=_KEY,
    )
    candidate = Candidate(
        chat_id="-1000000000000",
        message_id="m1",
        text="anyone know a good pizza place near the station?",
        user_name="Alex",
    )
    recent = [("Babi", "we should go friday"), ("Dia", "the one by the station is decent")]
    state = build_state(candidate, recent, config=CascadeConfig())

    try:
        answers = client.ask(state, build_questions())
    except JevError as exc:
        if "429" in str(exc) or "FreeUsageLimit" in str(exc):
            pytest.skip(f"jev free-tier rate limit reached: {exc}")
        if "transport error" in str(exc) or _is_transient_service_error(exc):
            pytest.skip(f"jev service transiently unhealthy: {exc}")
        pytest.fail(f"live cascade batch failed: {exc}")

    ids = {q["id"] for q in build_questions()}
    assert ids <= set(answers), f"missing answers: {ids - set(answers)}"
    # The composite must be computable end-to-end from the live answers.
    decision = compose(answers, config=CascadeConfig(), reactions_enabled=False)
    assert decision.action in {"message", "reaction", "silent"}
    assert 0.0 <= decision.value <= 1.0

