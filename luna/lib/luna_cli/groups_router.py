"""Authenticated dashboard routes for scoped group knowledge."""
import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from luna_cli import groups

router = APIRouter()


class NotesUpdate(BaseModel):
    entries: list[str] = Field(max_length=1000)
    revision: str = Field(min_length=64, max_length=64)


class PersonUpdate(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    revision: str | None = None
    inherit: bool = False


async def run(function, *args):
    try:
        return await asyncio.to_thread(function, *args)
    except groups.Conflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/groups")
async def list_groups():
    return await run(groups.bundle)


@router.get("/groups/{group_id}")
async def get_group(group_id: str):
    return await run(groups.bundle, group_id)


@router.put("/groups/{group_id}/notes")
async def save_notes(group_id: str, body: NotesUpdate):
    return await run(groups.update_notes, group_id, body.entries, body.revision)


@router.put("/groups/{group_id}/people/{user_id}")
async def save_person(group_id: str, user_id: str, body: PersonUpdate):
    return await run(groups.update_person, group_id, user_id, body.values, body.revision, body.inherit)


@router.get("/people/scopes")
async def get_people_scopes():
    return await run(groups.people_bundle)
