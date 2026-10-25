"""Dashboard-only portable profile operations, under the shared Luna auth/profile gate."""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request

from luna_cli import profile_transfer

router = APIRouter(prefix="/profiles")


async def _body(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > profile_transfer.MAX_BYTES:
            raise HTTPException(413, "Profile file exceeds the 2 MiB limit")
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise HTTPException(400, "Choose a valid Luna profile JSON file") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "Expected a profile request object")
    return value


async def _call(function, *args):
    try:
        return await asyncio.to_thread(function, *args)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{name}/export")
async def export_profile(name: str):
    return await _call(profile_transfer.export_profile, name)


@router.post("/preview")
async def preview(request: Request):
    body = await _body(request)
    return await _call(profile_transfer.preview, body.get("bundle"))


@router.post("/import")
async def import_profile(request: Request):
    body = await _body(request)
    name = body.get("name")
    if not isinstance(name, str):
        raise HTTPException(400, "Choose a new profile name")
    return await _call(profile_transfer.import_profile, name, body.get("bundle"))
