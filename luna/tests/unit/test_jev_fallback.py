"""jev fallback chain: primary first, paid route only when the primary is exhausted."""

from __future__ import annotations

import pytest

from luna_core.jev import (
    FallbackJevClient,
    JevClient,
    JevError,
    normalize_fallback_entries,
    resolve_jev_chain,
)


def _client(**kw) -> JevClient:
    return JevClient(api_key="primary-key", model="jev-1.13-free", **kw)


class _Boom:
    """Stands in for a client that fails a fixed number of times."""

    def __init__(self, exc: Exception, times: int = 99, model: str = "m"):
        self.exc = exc
        self.times = times
        self.model = model
        self.calls = 0

    def ask(self, state, questions):
        self.calls += 1
        if self.calls <= self.times:
            raise self.exc
        return {"ok": {}}


def test_normalize_accepts_a_single_dict_or_a_list():
    single = {"provider": "openrouter", "model": "typesafe/jev-1.13"}
    assert normalize_fallback_entries(single) == [single]
    assert normalize_fallback_entries([single, {"model": "x"}])[0]["provider"] == "openrouter"
    # Entries without a model are unusable and dropped.
    assert normalize_fallback_entries([{"provider": "p"}]) == []
    assert normalize_fallback_entries(None) == []


def test_primary_is_used_when_it_works():
    primary = _Boom(None, times=0, model="jev-1.13-free")
    fb = _Boom(None, times=0, model="paid")
    chain = FallbackJevClient(primary, [{"provider": "openrouter", "model": "typesafe/jev-1.13"}],
                              client_factory=lambda e: fb)
    assert chain.ask({}, []) == {"ok": {}}
    assert chain.served_by.startswith("jev-1.13-free")
    assert fb.calls == 0


def test_rate_limit_falls_back_to_the_paid_route():
    primary = _Boom(JevError("HTTP 429: FreeUsageLimitError", status=429))
    chain = FallbackJevClient(
        primary,
        [{"provider": "openrouter", "model": "typesafe/jev-1.13", "api_key_env": "OR_KEY"}],
        api_key_resolver=lambda env: {"OR_KEY": "or-key"}[env],
        client_factory=lambda e: _Boom(None, times=0, model=e["model"]),
    )
    assert chain.ask({}, []) == {"ok": {}}          # served by the fallback
    assert "typesafe/jev-1.13" in chain.served_by


def test_a_bad_request_does_not_burn_the_paid_route():
    """A 400 is our bug, not an exhausted quota — do not spend money on it."""
    primary = _Boom(JevError("HTTP 400: bad request", status=400))
    chain = FallbackJevClient(
        primary,
        [{"provider": "openrouter", "model": "typesafe/jev-1.13", "api_key_env": "OR_KEY"}],
        api_key_resolver=lambda env: "or-key",
    )
    with pytest.raises(JevError):
        chain.ask({}, [])
    assert chain.served_by == ""      # never advanced


def test_a_malformed_response_does_not_burn_the_paid_route():
    """A 200 with garbage fields is our bug — never advance past the primary for it."""
    primary = _Boom(JevError("answer for 'q' has malformed fields: bad", status=None))
    chain = FallbackJevClient(
        primary,
        [{"provider": "openrouter", "model": "paid", "api_key_env": "K"}],
        api_key_resolver=lambda env: "k",
        client_factory=lambda e: _Boom(None, times=0, model="paid"),
    )
    with pytest.raises(JevError):
        chain.ask({}, [])
    assert chain.served_by == ""      # never advanced
    assert chain._index == 0


def test_unexpected_exceptions_do_not_burn_the_paid_route():
    """Only retryable transport failures advance the chain; a bare ValueError is a bug."""
    primary = _Boom(ValueError("float() arg is not a number"))
    chain = FallbackJevClient(
        primary,
        [{"provider": "openrouter", "model": "paid", "api_key_env": "K"}],
        api_key_resolver=lambda env: "k",
        client_factory=lambda e: _Boom(None, times=0, model="paid"),
    )
    with pytest.raises(ValueError):
        chain.ask({}, [])
    assert chain._index == 0


def test_raw_transport_oserror_still_falls_back():
    """An unwrapped OSError from a custom transport is transport-class: a different host may work."""
    primary = _Boom(OSError("connection reset"))
    chain = FallbackJevClient(
        primary,
        [{"provider": "openrouter", "model": "paid", "api_key_env": "K"}],
        api_key_resolver=lambda env: "k",
        client_factory=lambda e: _Boom(None, times=0, model="paid"),
    )
    assert chain.ask({}, []) == {"ok": {}}
    assert "paid" in chain.served_by


def test_exhausted_chain_reraises_the_last_error():
    primary = _Boom(JevError("HTTP 429", status=429))
    chain = FallbackJevClient(primary, [{"provider": "openrouter", "model": "x",
                                         "api_key_env": "K"}],
                              api_key_resolver=lambda env: "k",
        client_factory=lambda e: _Boom(JevError("HTTP 429", status=429), model="x"))
    # The fallback also fails -> the error surfaces and the caller fails closed.
    with pytest.raises(JevError):
        chain.ask({}, [])


def test_switch_is_announced_once_and_resets():
    switches = []
    primary = _Boom(JevError("HTTP 429", status=429), times=1)
    chain = FallbackJevClient(
        primary, [{"provider": "openrouter", "model": "paid", "api_key_env": "K"}],
        api_key_resolver=lambda env: "k", on_switch=lambda a, b: switches.append((a, b)),
        client_factory=lambda e: _Boom(None, times=0, model="paid"),
    )
    chain.ask({}, [])
    assert switches and switches[0][1].startswith("paid")
    chain.reset()
    assert chain.served_by == "" and chain._index == 0


def test_transport_failure_also_falls_back():
    primary = _Boom(JevError("transport error: connection reset", status=None))
    chain = FallbackJevClient(primary, [{"provider": "openrouter", "model": "paid",
                                         "api_key_env": "K"}],
                              api_key_resolver=lambda env: "k",
                              client_factory=lambda e: _Boom(None, times=0, model="paid"))
    assert chain.ask({}, []) == {"ok": {}}
    assert "paid" in chain.served_by


def test_local_slot_absorbs_the_free_tier_rate_limit():
    """Shipped order is free -> local -> paid: a dead free tier is served by local, never paid."""
    primary = _Boom(JevError("HTTP 429: FreeUsageLimitError", status=429))
    local = _Boom(None, times=0, model="clm-latest")
    paid = _Boom(None, times=0, model="jev-latest")
    chain = FallbackJevClient(
        primary,
        [
            {"provider": "local", "model": "clm-latest",
             "base_url": "http://127.0.0.1:8700/v1"},
            {"provider": "typesafe", "model": "jev-latest",
             "base_url": "https://api.typesafe.ai/v1", "api_key_env": "TYPESAFE_API_KEY"},
        ],
        api_key_resolver=lambda env: "paid-key",
        client_factory=lambda e: local if e["provider"] == "local" else paid,
    )
    assert chain.ask({}, []) == {"ok": {}}
    assert local.calls == 1
    assert paid.calls == 0
    assert "clm-latest" in chain.served_by


def test_dead_local_slot_fails_over_to_paid():
    """Nothing listening on the local port (transport error) must reach the paid route."""
    primary = _Boom(JevError("HTTP 429: FreeUsageLimitError", status=429))
    local = _Boom(JevError("transport error: connection refused", status=None))
    paid = _Boom(None, times=0, model="jev-latest")
    chain = FallbackJevClient(
        primary,
        [
            {"provider": "local", "model": "clm-latest",
             "base_url": "http://127.0.0.1:8700/v1"},
            {"provider": "typesafe", "model": "jev-latest",
             "base_url": "https://api.typesafe.ai/v1", "api_key_env": "TYPESAFE_API_KEY"},
        ],
        api_key_resolver=lambda env: "paid-key",
        client_factory=lambda e: local if e["provider"] == "local" else paid,
    )
    assert chain.ask({}, []) == {"ok": {}}
    assert local.calls >= 1
    assert paid.calls == 1
    assert "jev-latest" in chain.served_by


def test_local_entry_keeps_base_url_and_needs_no_api_key_env():
    """A local entry is first-class in the chain: base_url preserved, api_key_env optional."""
    entries = normalize_fallback_entries([
        {"provider": "local", "model": "clm-latest", "base_url": "http://127.0.0.1:8700/v1"},
    ])
    assert entries == [{"provider": "local", "model": "clm-latest",
                        "base_url": "http://127.0.0.1:8700/v1"}]
    resolved = []
    chain = FallbackJevClient(_client(), entries,
                              api_key_resolver=lambda env: resolved.append(env) or "")
    built = chain._build(entries[0])
    # Keyless routes must never consult a resolver which could supply a default key.
    assert resolved == []
    assert built.api_key == ""
    assert built.base_url == "http://127.0.0.1:8700/v1"
    assert built.model == "clm-latest"


# -- named provider registry + route order (hermes-style) --------------------

REGISTRY = {
    "route": ["zen-free", "local", "typesafe"],
    "providers": {
        "zen-free": {"base_url": "https://opencode.ai/zen/v1", "model": "jev-1.13-free",
                     "api_key_env": "OPENCODE_ZEN_API_KEY"},
        "local": {"base_url": "http://127.0.0.1:8700/v1", "model": "clm-latest"},
        "typesafe": {"base_url": "https://api.typesafe.ai/v1", "model": "jev-latest",
                     "api_key_env": "TYPESAFE_API_KEY"},
    },
}


def test_route_list_is_the_order_and_route_names_follow_it():
    chain = resolve_jev_chain(REGISTRY)
    assert [e["provider"] for e in chain] == ["zen-free", "local", "typesafe"]
    assert [e["model"] for e in chain] == ["jev-1.13-free", "clm-latest", "jev-latest"]
    # Reorder = reprioritise: first entry is the primary.
    offline = dict(REGISTRY, route=["local", "zen-free", "typesafe"])
    assert [e["provider"] for e in resolve_jev_chain(offline)][0] == "local"
    # Rename = swap: drop the local slot entirely.
    no_local = dict(REGISTRY, route=["zen-free", "typesafe"])
    assert [e["provider"] for e in resolve_jev_chain(no_local)] == ["zen-free", "typesafe"]


def test_unknown_route_names_are_skipped_not_fatal():
    chain = resolve_jev_chain(dict(REGISTRY, route=["nope", "zen-free", "also-nope", "local"]))
    assert [e["provider"] for e in chain] == ["zen-free", "local"]


def test_route_entries_may_be_inline_dicts_and_names_mixed():
    cfg = {"route": ["local", {"provider": "openrouter", "model": "typesafe/jev-1.13",
                               "base_url": "https://openrouter.ai/api/v1",
                               "api_key_env": "OR_KEY"}],
           "providers": REGISTRY["providers"]}
    chain = resolve_jev_chain(cfg)
    assert [e["provider"] for e in chain] == ["local", "openrouter"]
    assert chain[1]["base_url"] == "https://openrouter.ai/api/v1"


def test_legacy_flat_shape_still_resolves_and_accepts_names():
    cfg = {"base_url": "https://opencode.ai/zen/v1", "model": "jev-1.13-free",
           "api_key_env": "OPENCODE_ZEN_API_KEY",
           "fallbacks": ["local", {"provider": "typesafe", "model": "jev-latest",
                                   "api_key_env": "TYPESAFE_API_KEY"}],
           "providers": REGISTRY["providers"]}
    chain = resolve_jev_chain(cfg)
    assert [e["provider"] for e in chain] == ["primary", "local", "typesafe"]
    assert chain[0]["base_url"] == "https://opencode.ai/zen/v1"
    assert chain[1]["base_url"] == "http://127.0.0.1:8700/v1"


def test_per_route_timeout_seconds_override():
    entries = resolve_jev_chain(dict(REGISTRY, providers=dict(
        REGISTRY["providers"],
        local={"base_url": "http://127.0.0.1:8700/v1", "model": "clm-latest",
               "timeout_seconds": 60},
    )))
    chain = FallbackJevClient(_client(), entries[1:],
                              api_key_resolver=lambda env: "",
                              route_names=[e["provider"] for e in entries])
    built = chain._build(entries[1])
    assert built.timeout == 60
    assert chain.active_route == "zen-free"
    chain._index = 1
    assert chain.active_route == "local"
