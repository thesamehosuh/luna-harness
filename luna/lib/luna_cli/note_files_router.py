"""Note file routes inherit the dashboard token and profile scope."""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from luna_cli import note_files

router = APIRouter()


class FileUpdate(BaseModel):
    content: str = Field(max_length=262144)
    revision: str = Field(min_length=64, max_length=64)


async def call(function, *args):
    try:
        return await asyncio.to_thread(function, *args)
    except note_files.Conflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from None


@router.get('/note-files')
async def list_files():
    return await call(note_files.catalog)


@router.get('/note-files/{file_id}')
async def read_file(file_id: str):
    return await call(note_files.read, file_id)


@router.put('/note-files/{file_id}')
async def save_file(file_id: str, body: FileUpdate):
    return await call(note_files.save, file_id, body.content, body.revision)
