"""The verdict `via=` field reports cost class (free | local | paid), not route names."""

from __future__ import annotations

from luna_core.jev import FallbackJevClient, route_tier


def test_model_or_url_saying_free_is_free():
    assert route_tier({"model": "jev-1.13-free", "provider": "primary"}) == "free"
    assert route_tier({"model": "x", "base_url": "https://opencode.ai/zen/v1", "provider": "zen-free"}) == "free"


def test_loopback_or_private_host_is_local():
    assert route_tier({"model": "clm-latest", "base_url": "http://127.0.0.1:8700/v1"}) == "local"
    assert route_tier({"model": "laya", "base_url": "http://localhost:8009/v1"}) == "local"
    assert route_tier({"model": "laya", "base_url": "http://192.168.1.10:8009/v1"}) == "local"
    assert route_tier({"model": "laya", "provider": "local"}) == "local"


def test_remote_metered_route_is_paid():
    assert route_tier({"model": "typesafe/jev-1.13", "provider": "openrouter",
                       "base_url": "https://openrouter.ai/api"}) == "paid"
    assert route_tier({"model": "glm-5.3-flash", "base_url": "https://opencode.ai/zen/go/v1"}) == "paid"


def test_explicit_tier_wins():
    assert route_tier({"tier": "free", "model": "expensive-thing"}) == "free"
    assert route_tier({"tier": "local", "base_url": "https://remote.example"}) == "local"
    assert route_tier({"tier": "paid", "model": "something-free"}) == "paid"


class _Client:
    def __init__(self, model, base_url=""):
        self.model = model
        self.base_url = base_url


def test_fallback_client_exposes_the_serving_tier():
    chain = FallbackJevClient(
        _Client("jev-1.13-free", "https://opencode.ai/zen/v1"),
        [{"provider": "local", "model": "clm-latest", "base_url": "http://127.0.0.1:8700/v1"},
         {"provider": "openrouter", "model": "typesafe/jev-1.13", "base_url": "https://openrouter.ai/api"}],
        route_names=["zen-free", "local", "typesafe"],
    )
    assert chain.active_route == "zen-free"
    assert chain.active_tier == "free"
    chain._index = 1
    assert chain.active_route == "local"
    assert chain.active_tier == "local"
    chain._index = 2
    assert chain.active_route == "typesafe"
    assert chain.active_tier == "paid"
