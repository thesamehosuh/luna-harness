"""``/api/luna/*`` — the companion API (Behaviour + People dashboard pages).

Mounted by ``hermes_cli.web_server`` when the overlay is importable. Every route inherits the
dashboard's session-token/OAuth gate (the mount sits behind the same ``/api/`` middleware as the
engine routers); the models in :mod:`luna_cli.api_models` hold the actual read/write logic.

Two hardening layers sit on top of that middleware, because the middleware alone is a single point
of failure for all 22 routes: a router-level ``_require_token`` dependency (defense in depth — it is
a no-op in loopback mode where the gate is correctly off, and enforces the token where it is on),
and per-endpoint rate limits on the operations that can hold the server for minutes.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from luna_cli import api_models
from luna_cli import behaviour as behaviour_models
from luna_cli import character as character_models
from luna_cli import onboarding
from luna_cli import opencode


def _require_token(request: Request) -> None:
    """Late-bound so the engine's own gate (and a test's monkeypatch) decides, not a copy of it.

    Mirrors the engine routers' ``late("_require_token")`` seam: the engine function branches on
    ``app.state.auth_required``, so this is a no-op on loopback and a real check behind the gate.
    """
    from hermes_cli.web_server import _require_token as engine_require_token

    engine_require_token(request)


async def _profile_context(request: Request):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise HTTPException(status_code=415, detail="Expected application/json")
    from hermes_cli.web_server_profiles import _config_profile_scope
    with _config_profile_scope(request.query_params.get("profile")):
        yield


router = APIRouter(prefix="/api/luna", tags=["luna"], dependencies=[Depends(_require_token), Depends(_profile_context)])

from luna_cli.profile_transfer_router import router as profile_transfer_router

router.include_router(profile_transfer_router)


# ── Costly-operation rate limiting ────────────────────────────────────────────────────────────────
# /replay and /onboarding/honcho/up run a subprocess for up to 10-11 minutes, and /verdicts/stream
# holds a connection open indefinitely. Without a bound, one authenticated client (or a token read
# off a loopback port) can exhaust the thread pool. Same shape as the engine's env-reveal limiter.

_RATE_LOCK = threading.Lock()
_CALL_TIMES: Dict[str, List[float]] = {}

# endpoint -> (max calls, window seconds)
_RATE_LIMITS: Dict[str, tuple[int, float]] = {
    "replay": (3, 300.0),
    "honcho_up": (3, 600.0),
    "wake_test": (6, 300.0),
    "opencode_install": (3, 600.0),
    "opencode_probe": (6, 300.0),
}
_RATE_DEFAULTS = (10, 60.0)


def _rate_limit(name: str) -> None:
    limit, window = _RATE_LIMITS.get(name, _RATE_DEFAULTS)
    now = time.monotonic()
    cutoff = now - window
    with _RATE_LOCK:
        hits = [t for t in _CALL_TIMES.get(name, []) if t > cutoff]
        if len(hits) >= limit:
            _CALL_TIMES[name] = hits
            raise HTTPException(
                status_code=429,
                detail=f"Too many {name} requests. Try again in a few minutes.",
            )
        hits.append(now)
        _CALL_TIMES[name] = hits


# ── Request bodies ───────────────────────────────────────────────────────────────────────────────


class ThresholdUpdate(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


class IdentityUpsert(BaseModel):
    platform: str = "telegram"
    user_id: str
    peer_id: Optional[str] = None
    display_name: Optional[str] = None
    pronouns: Optional[str] = None
    aliases: Optional[List[str]] = None
    role: Optional[str] = None
    user_id_alt: Optional[str] = None


class IdentityMerge(BaseModel):
    primary: str
    alt: str
    platform: Optional[str] = None


class ReplayRequest(BaseModel):
    limit: int = 25
    recent: int = 10


class WakeTestRequest(BaseModel):
    live: bool = False


class HonchoUpRequest(BaseModel):
    timeout: int = Field(180, ge=30, le=600)


class MemoryServiceRequest(BaseModel):
    enabled: bool
    timeout: int = Field(180, ge=30, le=600)


class SoulSection(BaseModel):
    title: str
    body: str = ""


class CharacterUpdate(BaseModel):
    preset_id: Optional[str] = None
    soul_text: Optional[str] = None
    title: Optional[str] = None
    intro: Optional[str] = None
    sections: Optional[List[SoulSection]] = None
    footer: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    skin: Optional[str] = None
    skin_colors: Optional[Dict[str, str]] = None
    skin_description: Optional[str] = None
    auto_load: Optional[List[str]] = None


class PreviewRequest(BaseModel):
    text: str
    surface: str = "group"


class BehaviourUpdate(BaseModel):
    enabled: Optional[bool] = None
    dry_run: Optional[bool] = None
    room_register: Optional[str] = None
    settle_seconds: Optional[int] = None
    poll_seconds: Optional[int] = None
    stale_after_minutes: Optional[int] = None
    watched_chats: Optional[List[str]] = None
    budget: Optional[Dict[str, Optional[int]]] = None
    mention_fallback: Optional[List[str]] = None
    reactions: Optional[Dict[str, Any]] = None
    jev: Optional[Dict[str, Any]] = None
    conversation: Optional[Dict[str, Any]] = None
    decision: Optional[Dict[str, Any]] = None
    wake_prompts: Optional[Dict[str, Any]] = None


# ── Behaviour (wake tuning) ──────────────────────────────────────────────────────────────────────


@router.get("/health")
async def get_health():
    return api_models.health()


@router.get("/verdicts")
async def get_verdicts(limit: int = Query(50, ge=1, le=500)):
    events = api_models.verdicts(limit)
    return {"events": events, **api_models.verdict_log_state()}


_SSE_LOCK = threading.Lock()
_SSE_OPEN = 0
_SSE_MAX_CONNECTIONS = 8


@router.get("/verdicts/stream")
async def stream_verdicts():
    """Server-sent events: verdict events as they land in ``agent.log`` (tail -f)."""
    global _SSE_OPEN
    # Each stream holds a file handle and an asyncio task for as long as the client stays
    # connected, so an unbounded tail is a slow resource leak. A handful of concurrent viewers is
    # plenty for a single-operator dashboard.
    #
    # Resolve the path BEFORE taking a slot: anything that raises between the increment and the
    # generator's first iteration leaked a slot permanently, wedging this endpoint with a 429 until
    # restart (the release only happens inside the generator's finally).
    path = api_models.agent_log()
    with _SSE_LOCK:
        if _SSE_OPEN >= _SSE_MAX_CONNECTIONS:
            raise HTTPException(status_code=429, detail="Too many verdict streams open.")
        _SSE_OPEN += 1

    async def _events():
        # Open before the first yield so a missing file is a clean empty stream (the client
        # polls GET /verdicts for the historical tail either way).
        global _SSE_OPEN
        handle = None
        try:
            if path.exists():
                handle = path.open("r", encoding="utf-8", errors="replace")
                handle.seek(0, 2)
            while True:
                if handle is None:
                    await asyncio.sleep(2.0)
                    if path.exists():
                        handle = path.open("r", encoding="utf-8", errors="replace")
                        handle.seek(0, 2)
                    continue
                line = handle.readline()
                if not line:
                    await asyncio.sleep(1.0)
                    continue
                event = api_models.parse_verdict_line(line)
                if event:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            if handle is not None:
                handle.close()
            with _SSE_LOCK:
                _SSE_OPEN = max(0, _SSE_OPEN - 1)

    return StreamingResponse(_events(), media_type="text/event-stream")


@router.get("/wakes")
async def get_wakes(limit: int = Query(50, ge=1, le=500)):
    return {"wakes": api_models.wakes(limit)}


@router.get("/thresholds")
async def get_thresholds():
    return api_models.thresholds()


@router.put("/thresholds")
async def put_thresholds(body: ThresholdUpdate):
    result = api_models.set_thresholds(body.values)
    failed = {k: v for k, v in result["results"].items() if not v["ok"]}
    if failed:
        raise HTTPException(status_code=400, detail=failed)
    return result


@router.get("/cost")
async def get_cost(days: int = Query(0, ge=0, le=3650)):
    return api_models.cost(days)


@router.post("/replay")
async def post_replay(body: ReplayRequest):
    _rate_limit("replay")
    # asyncio.to_thread: replay shells out with a 600s timeout. Calling it inline from an async
    # def blocks the single event loop, so one replay freezes every other dashboard request (auth
    # middleware, status, the verdict tail) for the duration. The rate limit bounds how often this
    # starts; it does nothing about how long it blocks.
    result = await asyncio.to_thread(api_models.replay, body.limit, body.recent)
    if not result.get("ok") and result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ── People (identity registry) ───────────────────────────────────────────────────────────────────


@router.get("/identity")
async def get_identity(platform: Optional[str] = Query(None)):
    return {"identities": api_models.identity_list(platform)}


@router.post("/identity")
async def post_identity(body: IdentityUpsert):
    result = api_models.identity_upsert(body.platform, body.user_id, body.model_dump(exclude_unset=True))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "identity write failed"))
    return result


@router.post("/identity/merge")
async def post_identity_merge(body: IdentityMerge):
    result = api_models.identity_merge(body.primary, body.alt, body.platform)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/peers/audit")
async def get_peers_audit():
    return api_models.peers_audit()


@router.get("/people")
async def get_people_directory():
    def read_directory():
        from luna_core import people
        conn, registry = api_models._registry()
        try:
            entries = people.refresh(registry)
            return {"text": people.path().read_text(encoding="utf-8"), "count": sum(len(key) == 2 for key in entries)}
        finally:
            conn.close()
    try:
        return await asyncio.to_thread(read_directory)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/peers/sync")
async def post_peers_sync(request: Request, platform: Optional[str] = Query(None)):
    # This endpoint takes no model body, so its Content-Type is the only thing distinguishing it
    # from a cross-site HTML form POST. Requiring JSON means a form can no longer match its shape,
    # which keeps SameSite=Lax from being the *sole* CSRF control on a state-changing route.
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise HTTPException(status_code=415, detail="Expected application/json.")
    # Sync + network (Honcho): never call inline from an async def.
    return await asyncio.to_thread(api_models.peers_sync, platform)


# ── Character + Behaviour (PRODUCT_PLAN P4) ──────────────────────────────────────────────────────


@router.get("/character")
async def get_character():
    return character_models.character_bundle()


async def _put_character(body: CharacterUpdate):
    out: Dict[str, Any] = {}
    if body.preset_id is not None:
        preset = next((p for p in character_models.personas() if p["id"] == body.preset_id), None)
        if preset is None:
            raise HTTPException(status_code=404, detail=f"unknown persona preset {body.preset_id!r}")
        out["soul"] = character_models.write_soul_text(preset["content"])
    elif body.sections is not None or body.soul_text is not None:
        try:
            if body.soul_text is not None:
                out["soul"] = character_models.write_soul_text(body.soul_text)
            else:
                out["soul"] = character_models.write_soul(
                    title=body.title, intro=body.intro,
                    sections=[s.model_dump() for s in body.sections or []],
                    footer=body.footer,
                )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.output is not None:
        result = character_models.write_output_limits(body.output)
        out["output"] = result
        if any(not r.get("ok") for r in result["results"].values()):
            raise HTTPException(status_code=400, detail=result["results"])
    if body.skin is not None:
        result = character_models.set_skin(body.skin)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "skin write failed"))
        out["skin"] = result
    if body.skin_colors is not None:
        target = body.skin or character_models.current_skin()
        result = character_models.write_skin(target, body.skin_colors, body.skin_description)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "skin write failed"))
        out["skin_colors"] = result
    if body.auto_load is not None:
        result = character_models.set_auto_load(body.auto_load)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "skills write failed"))
        out["auto_load"] = result
    out["bundle"] = character_models.character_bundle()
    return out


@router.put("/character")
async def put_character(body: CharacterUpdate, request: Request):
    from luna_core import settings
    try:
        with settings.transaction(request.headers.get("if-match")):
            result = await _put_character(body)
        result["bundle"] = character_models.character_bundle()
        return result
    except settings.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/character/preview")
async def post_character_preview(body: PreviewRequest):
    return character_models.preview_shaping(body.text, body.surface)


@router.get("/behaviour")
async def get_behaviour():
    return behaviour_models.behaviour_bundle()


@router.put("/behaviour")
async def put_behaviour(body: BehaviourUpdate, request: Request):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="empty update")
    from luna_core import settings
    try:
        with settings.transaction(request.headers.get("if-match")):
            result = behaviour_models.write_behaviour(updates)
    except settings.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result["results"] and any(not v["ok"] for v in result["results"].values()):
        raise HTTPException(status_code=400, detail=result["results"])
    return result


# ── Onboarding wizard (PRODUCT_PLAN P3) ──────────────────────────────────────────────────────────


@router.get("/onboarding")
async def get_onboarding():
    return onboarding.step_report()


class TelegramDestinationsRequest(BaseModel):
    owner_id: str
    group_chat_id: Optional[str] = None
    home_target: Literal["owner", "group", "keep"] = "keep"


@router.put("/onboarding/telegram")
async def put_telegram_destinations(body: TelegramDestinationsRequest):
    try:
        return await asyncio.to_thread(onboarding.configure_telegram_destinations, body.owner_id, body.group_chat_id, body.home_target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class SetupChoiceRequest(BaseModel):
    step: Literal["honcho", "wake_test", "telegram"]
    choice: Literal["enabled", "skipped"]


@router.put("/onboarding/choice")
async def put_setup_choice(body: SetupChoiceRequest):
    return await asyncio.to_thread(onboarding.set_choice, body.step, body.choice)


@router.get("/onboarding/memory/reasoning")
async def get_memory_reasoning():
    from luna_core.memory_reasoning import public_route
    return await asyncio.to_thread(public_route)


@router.get("/onboarding/memory/progress")
async def get_memory_progress():
    from luna_core.managed_memory import status
    return await asyncio.to_thread(status)


@router.get("/memory/settings")
async def get_memory_settings():
    from luna_cli.memory_settings import report
    return await asyncio.to_thread(report)


@router.post("/memory/service")
async def post_memory_service(body: MemoryServiceRequest):
    _rate_limit("honcho_up")
    try:
        result = await asyncio.to_thread(onboarding.set_memory_service, body.enabled, body.timeout)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("detail", "Honcho could not be started."))
    return result


@router.get("/desktop/identity")
async def get_desktop_identity(request: Request):
    """Authenticated per-spawn proof, not a port-only readiness probe."""
    import os
    from luna_core.runtime import home
    from hermes_cli.product_runtime import version
    nonce = os.environ.get("LUNA_DESKTOP_NONCE")
    if not nonce:
        raise HTTPException(status_code=404, detail="No desktop owner")
    from hermes_cli.web_server import _has_valid_session_token
    if not _has_valid_session_token(request):
        raise HTTPException(status_code=401, detail="Invalid desktop session")
    return {"product": "Luna", "version": version(), "home": str(home().resolve()), "nonce": nonce}


class OpenCodeModelRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200, pattern=r"^opencode/[a-zA-Z0-9._:-]+$")


async def _opencode_call(callback, *args):
    try:
        return await asyncio.to_thread(callback, *args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except (OSError, RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("/opencode")
async def get_opencode():
    return await _opencode_call(opencode.status)


@router.post("/opencode/install")
async def post_opencode_install():
    _rate_limit("opencode_install")
    return await _opencode_call(opencode.install_engine)


@router.get("/opencode/models")
async def get_opencode_models():
    _rate_limit("opencode_models")
    return await _opencode_call(opencode.catalog)


@router.put("/opencode/model")
async def put_opencode_model(body: OpenCodeModelRequest):
    return await _opencode_call(opencode.select_model, body.model)


@router.post("/opencode/probe")
async def post_opencode_probe(body: OpenCodeModelRequest):
    _rate_limit("opencode_probe")
    return await _opencode_call(opencode.probe, body.model)


@router.get("/onboarding/personas")
async def get_onboarding_personas():
    return {"personas": onboarding.personas()}


@router.post("/onboarding/honcho/up")
async def post_onboarding_honcho_up(body: HonchoUpRequest):
    _rate_limit("honcho_up")
    # docker compose + health probe — off the event loop.
    return await asyncio.to_thread(onboarding.honcho_up, body.timeout)


@router.post("/onboarding/wake-test")
async def post_onboarding_wake_test(body: WakeTestRequest):
    # A live run spends one jev judgment; the dry-run stops at stage 0.
    if body.live:
        _rate_limit("wake_test")
    return await asyncio.to_thread(onboarding.run_wake_test, body.live)


@router.get("/data")
async def get_data_status():
    from luna_core import data_ops, retention, readiness
    from luna_core.runtime import home
    root = home()
    from pathlib import Path
    manifest = Path(__file__).resolve().parents[3] / "luna-release.json"
    product = json.loads(manifest.read_text()) if manifest.exists() else {}
    from hermes_cli.product_runtime import installation_home
    install = installation_home(root)
    try:
        pointer = json.loads((install / "current-release.json").read_text())
    except (OSError, ValueError):
        pointer = {}
    previous = pointer.get("previous") or {}
    try:
        native = json.loads((root / ".native-status.json").read_text())
    except (OSError, ValueError):
        native = None
    return {"product": product, "inventory": data_ops.INVENTORY, "retention": retention.status(), "delivery": api_models.memory_delivery(),
            "chat_check": readiness.get("chat"), "memory_check": readiness.get("memory"), "native": native,
            "backups": sorted([p.name for p in (root / "backups/luna").glob("*.tar.gz")], reverse=True),
            "release": pointer.get("version") or (str((install / "current").resolve().name) if (install / "current").is_symlink() else None),
            "rollback_available": (install / previous.get("path", "no-previous") / ".ready").is_file() or (install / "previous/.ready").exists()}


@router.post("/data/retention")
async def post_retention():
    _rate_limit("retention")
    from luna_core.retention import enforce
    return await asyncio.to_thread(enforce)


@router.post("/data/verify-memory")
async def post_verify_memory():
    _rate_limit("verify_memory")
    from luna_core.readiness import verify_memory
    return await _opencode_call(verify_memory)


@router.post("/data/backup")
async def post_backup():
    _rate_limit("backup")
    from luna_core.data_ops import backup
    return await _opencode_call(backup)


@router.get("/data/backups/{name}")
async def download_data_backup(name: str):
    from fastapi.responses import FileResponse
    from luna_core.runtime import home
    from pathlib import Path
    if Path(name).name != name or not name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Invalid backup name")
    path = home() / "backups/luna" / name
    if not path.is_file() or path.is_symlink():
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(path, filename=name, media_type="application/gzip")


class RestoreRequest(BaseModel):
    name: str


@router.post("/data/restore")
async def post_restore(body: RestoreRequest):
    _rate_limit("restore")
    from luna_core.data_ops import restore
    return await _opencode_call(restore, body.name)


@router.post("/data/rollback")
async def post_release_rollback():
    from luna_core.data_ops import require_stopped
    from luna_core.runtime import home
    from hermes_cli.product_runtime import installation_home
    if (installation_home(home()) / "current-release.json").is_file():
        from luna_core.release_control import rollback
        return {**(await _opencode_call(rollback)), "restart_required": True}
    require_stopped()
    import importlib.util
    import sys
    directory = home() / "luna/deploy"
    if not directory.exists():
        raise HTTPException(status_code=400, detail="No versioned installation is available")
    # Imported by path because deployment tools are intentionally outside the Python package.
    spec = importlib.util.spec_from_file_location("luna_release_ops", directory / "releases.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(directory))
    try:
        spec.loader.exec_module(module)
        module.rollback(home())
    finally:
        sys.path.remove(str(directory))
    return {"ok": True, "restart_required": True}


@router.post("/data/verify-chat")
async def post_verify_chat():
    _rate_limit("verify_chat")
    from luna_core.readiness import verify_chat
    return await _opencode_call(verify_chat)


@router.post("/data/retry-delivery")
async def post_retry_delivery():
    _rate_limit("retry_delivery")
    from luna_core import db
    conn = db.connect(api_models.db_path())
    try:
        db.init_db(conn)
        conn.execute("UPDATE memory_outbox SET state='pending' WHERE state='uncertain'")
        conn.execute("DELETE FROM meta WHERE key LIKE 'memory_retry:%'")
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "detail": "Held deliveries will be reconciled before retrying. Remote lookup must succeed first."}
