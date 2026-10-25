"""Hardening controls added in the P6 pass (dashboard-side).

Covers the three classes of fix: per-endpoint cost limiting on the multi-minute operations,
a connection cap on the verdict SSE tail, and the Content-Type guard that keeps a bodyless
state-changing route from matching a cross-site form POST.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "luna" / "lib"))


@pytest.fixture()
def routers(monkeypatch):
    """A freshly imported overlay router module with cleared limiter state."""
    for name in [n for n in sys.modules if n == "luna_cli.web_routers"]:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        "luna_web_routers_hardening", REPO_ROOT / "luna" / "lib" / "luna_cli" / "web_routers.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    mod._CALL_TIMES.clear()
    yield mod
    mod._CALL_TIMES.clear()


# ── Cost limiting ────────────────────────────────────────────────────────────────────────────────


def test_rate_limit_blocks_the_caller_after_the_budget(routers):
    """A single caller must not be able to queue unbounded 10-minute replays."""
    limit, _window = routers._RATE_LIMITS["replay"]
    for _ in range(limit):
        routers._rate_limit("replay")
    with pytest.raises(HTTPException) as exc:
        routers._rate_limit("replay")
    assert exc.value.status_code == 429


def test_rate_limit_is_per_endpoint(routers):
    """Exhausting replay must not lock the operator out of honcho/up."""
    limit, _ = routers._RATE_LIMITS["replay"]
    for _ in range(limit):
        routers._rate_limit("replay")
    routers._rate_limit("honcho_up")  # independent budget


# ── SSE connection cap ───────────────────────────────────────────────────────────────────────────


def test_sse_connection_cap_refuses_the_ninth_stream(routers, monkeypatch):
    import asyncio

    monkeypatch.setattr(routers, "_SSE_OPEN", routers._SSE_MAX_CONNECTIONS)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routers.stream_verdicts())
    assert exc.value.status_code == 429


def test_sse_cap_counter_is_not_leaked_by_a_refusal(routers, monkeypatch):
    """A refused connection must not consume a slot, or the dashboard wedges itself."""
    import asyncio

    monkeypatch.setattr(routers, "_SSE_OPEN", routers._SSE_MAX_CONNECTIONS)
    with pytest.raises(HTTPException):
        asyncio.run(routers.stream_verdicts())
    assert routers._SSE_OPEN == routers._SSE_MAX_CONNECTIONS


# ── CSRF shape guard ─────────────────────────────────────────────────────────────────────────────


def test_peers_sync_requires_a_json_content_type(routers):
    """A state-changing route that accepts a bodyless POST matches a cross-origin primitive.

    An HTML form always sends urlencoded/multipart, and a cross-origin ``mode: "no-cors"`` fetch
    sends no Content-Type at all. Both are rejected, so ``SameSite=Lax`` is not the only control.
    """
    import asyncio

    class _Req:
        def __init__(self, ctype):
            self.headers = {"content-type": ctype} if ctype is not None else {}

    for hostile in ("application/x-www-form-urlencoded", "multipart/form-data", "text/plain", None):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(routers.post_peers_sync(_Req(hostile)))
        assert exc.value.status_code == 415, f"{hostile} was accepted"

    # Stub the sync: the real one opens the operator's luna-state.db, may rewrite honcho.json and
    # attempts a live HTTP call to the local Honcho stack.
    routers.api_models.peers_sync = lambda platform=None: {"ok": True}
    assert asyncio.run(routers.post_peers_sync(_Req("application/json; charset=utf-8"))) == {"ok": True}


# ── Wiring: the limits must actually be ON the routes, not just present in a dict ────────────────
#
# Deleting every `_rate_limit(...)` call site leaves the direct `_rate_limit()` tests above green,
# so the wiring needs its own coverage.


def _server():
    from hermes_cli import web_server

    return web_server


@pytest.fixture()
def client(routers, monkeypatch):
    """The overlay router on a bare app: no middleware, so only the route's own limit can 429."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    # Loopback mode: the gate is legitimately off, so _require_token is a no-op — exactly what the
    # dashboard does on 127.0.0.1. Without this the router's own dependency 401s every call, which
    # is itself proof the dependency is wired.
    app.state.auth_required = False
    app.include_router(routers.router)
    # The endpoints do real work; stub every one the rate-limit tests touch.
    monkeypatch.setattr(
        routers.api_models, "replay", lambda limit, recent: {"ok": True, "ran": "replay"}
    )
    monkeypatch.setattr(routers.onboarding, "honcho_up", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(routers.onboarding, "run_wake_test", lambda live: {"ok": True})
    routers._CALL_TIMES.clear()
    client = TestClient(app)
    # Loopback mode still requires the session token from the caller (the SPA sends it on every
    # /api/ call); only the *gate* is off.
    client.headers["X-Hermes-Session-Token"] = _server()._active_session_token()
    return client


def test_replay_endpoint_is_rate_limited(client, routers):
    limit = routers._RATE_LIMITS["replay"][0]
    for _ in range(limit):
        assert client.post("/api/luna/replay", json={}).status_code == 200
    assert client.post("/api/luna/replay", json={}).status_code == 429


def test_honcho_up_endpoint_is_rate_limited(client, routers):
    limit = routers._RATE_LIMITS["honcho_up"][0]
    for _ in range(limit):
        assert client.post("/api/luna/onboarding/honcho/up", json={}).status_code == 200
    assert client.post("/api/luna/onboarding/honcho/up", json={}).status_code == 429


def test_only_live_wake_tests_are_rate_limited(client, routers):
    """A dry run spends no jev call and must stay free; the live one is capped."""
    for _ in range(20):
        assert client.post("/api/luna/onboarding/wake-test", json={"live": False}).status_code == 200
    limit = routers._RATE_LIMITS["wake_test"][0]
    for _ in range(limit):
        assert client.post("/api/luna/onboarding/wake-test", json={"live": True}).status_code == 200
    assert client.post("/api/luna/onboarding/wake-test", json={"live": True}).status_code == 429


def test_router_rejects_an_unauthenticated_call(client, routers):
    """End-to-end proof the dependency is live: the bare app has no middleware, so a 401 here can
    only come from the route's own `_require_token`. On the real app the `/api/` middleware 401s
    first, which is why this could not be covered there."""
    bare = client.headers.pop("X-Hermes-Session-Token")
    try:
        assert client.get("/api/luna/health").status_code == 401
        client.headers["X-Hermes-Session-Token"] = "wrong-token"
        assert client.get("/api/luna/health").status_code == 401
    finally:
        client.headers["X-Hermes-Session-Token"] = bare
    assert client.get("/api/luna/health").status_code == 200


def test_router_declares_the_token_dependency(routers):
    """Second auth layer behind the middleware.

    The dashboard's `/api/` middleware 401s before routing, so every route test passes whether or
    not this dependency exists. Assert it is declared so a future refactor cannot silently drop the
    only defence if the mount or the middleware changes.
    """
    names = [getattr(dep.dependency, "__name__", "") for dep in routers.router.dependencies]
    assert "_require_token" in names, f"router-level auth dependency missing: {names}"


def test_expensive_endpoints_do_not_block_the_event_loop(routers):
    """These run a subprocess / reach the network; calling them inline from an async def freezes
    every other dashboard request for the duration (up to 600s for a replay)."""
    import inspect

    for handler in (
        routers.post_replay,
        routers.post_peers_sync,
        routers.post_onboarding_honcho_up,
    ):
        source = inspect.getsource(handler)
        # A bare `return api_models.<sync call>` means it ran on the event loop.
        assert "await asyncio.to_thread(" in source, (
            f"{handler.__name__} calls blocking work inline from an async def"
        )
