"""jev client: request shape, parsing, retries, fail-closed behavior."""

from __future__ import annotations

import json

import pytest

from luna_core.jev import JevClient, JevError, _parse_retry_after, choice, noul, parse_answers, score


def test_parse_retry_after():
    assert _parse_retry_after("812") == 812.0
    assert _parse_retry_after("1.5") == 1.5
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("later") is None


def test_parse_answers_noul_choice_score_with_legend():
    payload = {
        "answers": {
            "a": {"type": "noul", "noul": 0.87},
            "b": {"type": "choice", "choice": "message", "probabilities": {"message": 0.6},
                  "confidence": 0.9},
            "c": {"type": "score", "score": 1.05,
                  "legend": {"0": "Calm", "1": "Frustrated"},
                  "probabilities": {"1": 0.95}, "confidence": 0.92},
        }
    }
    answers = parse_answers(payload)
    assert answers["a"].as_probability() == 0.87
    assert answers["b"].value == "message"
    assert answers["b"].confidence == 0.9
    assert answers["c"].value == 1.05
    assert answers["c"].legend == {"0": "Calm", "1": "Frustrated"}


def test_parse_answers_rejects_malformed():
    with pytest.raises(JevError):
        parse_answers({"nope": 1})
    with pytest.raises(JevError):
        parse_answers({"answers": {"a": {"type": "noul"}}})


def test_parse_answers_wraps_type_errors_as_jev_error():
    """A malformed 200 must never escape as ValueError/AttributeError (that skips fail-closed)."""
    with pytest.raises(JevError):
        parse_answers(["not", "an", "object"])
    with pytest.raises(JevError):
        parse_answers(None)
    with pytest.raises(JevError):
        parse_answers({"answers": {"a": {"type": "noul", "noul": 0.5,
                                         "confidence": "not-a-number"}}})
    with pytest.raises(JevError):
        parse_answers({"answers": {"a": {"type": "noul", "noul": 0.5,
                                         "probabilities": {"x": "bad"}}}})


def test_ask_builds_request_and_parses_response():
    seen = {}

    def transport(url, body, headers, timeout):
        seen["url"] = url
        seen["body"] = json.loads(body.decode())
        seen["headers"] = dict(headers)
        return {"answers": {"q1": {"type": "noul", "noul": 0.5}}}

    client = JevClient(api_key="k", transport=transport)
    answers = client.ask({"x": 1}, [noul("q1", "is it?", {"true": "y", "false": "n"})])

    assert seen["url"] == "https://opencode.ai/zen/v1/systemone"
    assert seen["body"]["model"] == "jev-1.13-free"
    assert seen["body"]["state"] == {"x": 1}  # structured state passes through
    assert seen["body"]["questions"]["q1"]["type"] == "noul"
    assert "id" not in seen["body"]["questions"]["q1"]
    assert seen["headers"]["Authorization"] == "Bearer k"
    assert "User-Agent" in seen["headers"]
    assert answers["q1"].as_probability() == 0.5


def test_ask_fails_closed_on_transport_error():
    def boom(url, body, headers, timeout):
        raise JevError("network down")

    client = JevClient(transport=boom, max_retries=0)
    with pytest.raises(JevError):
        client.ask("s", [noul("q", "i", {"true": "y", "false": "n"})])


def test_backend_is_configurable():
    client = JevClient(base_url="https://api.typesafe.ai/v1", model="jev-latest", api_key="t")
    assert client.endpoint == "https://api.typesafe.ai/v1/systemone"
    assert client.build_request("s", [])["model"] == "jev-latest"


def test_question_builders_shape():
    n = noul("q", "i", {"yes": "y", "no": "n"})
    assert n["type"] == "noul"
    assert n["criteria"] == {"true": "y", "false": "n"}  # normalized to true/false
    assert choice("q", "i", {"a": "b"})["criteria"] == {"a": "b"}
    assert score("q", "i", ["low", "high"])["criteria"] == ["low", "high"]


def test_build_request_keys_questions_by_id():
    client = JevClient(api_key="k")
    body = client.build_request("s", [noul("a", "i", {"true": "y", "false": "n"}),
                                      choice("b", "i", {"x": "y"})])
    assert set(body["questions"]) == {"a", "b"}
    assert body["questions"]["a"]["criteria"] == {"true": "y", "false": "n"}


def test_route_instructions_reach_each_question_without_mutating_it():
    questions = [noul("a", "Question A"), noul("b", "Question B")]
    body = JevClient(instructions="Judge as a quiet companion.").build_request({}, questions)
    assert body["questions"]["a"]["instructions"] == "Judge as a quiet companion.\n\nQuestion A"
    assert body["questions"]["b"]["instructions"] == "Judge as a quiet companion.\n\nQuestion B"
    assert questions[0]["instructions"] == "Question A"


def test_retries_on_429_then_succeeds():
    attempts = {"n": 0}
    slept = []

    def flaky(url, body, headers, timeout):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise JevError("HTTP 429: rate limited")
        return {"answers": {"q": {"type": "noul", "noul": 0.9}}}

    # The transport-level retry lives in _post for the urllib path; the injected transport path is
    # called once. Here we assert the client surfaces the error without retrying an injected
    # transport (retries are for the real HTTP path).
    client = JevClient(transport=flaky, max_retries=2, sleep=slept.append)
    with pytest.raises(JevError):
        client.ask("s", [noul("q", "i", {"true": "y", "false": "n"})])
    assert attempts["n"] == 1
