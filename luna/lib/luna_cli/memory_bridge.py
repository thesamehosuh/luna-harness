"""Per-home authenticated Honcho bridge: local embeddings and selected reasoning.

Docker reaches this host worker using host.docker.internal. Every endpoint requires
the generated stack credential; no dashboard/companion tools or history are loaded.
"""
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import os
from pathlib import Path
import socket
import time


def create_app(token, record, ready, *, embedder=None):
    from fastapi import FastAPI, HTTPException, Request
    from luna_core.embeddings import Embedder, MODEL
    from luna_core import config_read
    from luna_core.memory_reasoning import complete
    from luna_core.settings import _replace
    local = embedder or Embedder()
    @asynccontextmanager
    async def lifespan(app):
        _replace(ready, json.dumps(record))
        yield
        try:
            if json.loads(ready.read_text()).get("nonce") == record["nonce"]:
                ready.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    slots = asyncio.Semaphore(2)
    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        from starlette.responses import JSONResponse
        value = request.headers.get("authorization", "")
        if not hmac.compare_digest(value, "Bearer " + token):
            return JSONResponse({"error": {"message": "Unauthorized"}}, status_code=401)
        return await call_next(request)
    @app.get("/health")
    async def health():
        return {"ok": True, "nonce": record["nonce"], "home": record["home"], "model": MODEL["id"], "dimensions": MODEL["dimensions"], "release": record.get("release")}
    async def body(request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 1_000_000:
                raise HTTPException(413, "Memory request is too large")
        try:
            value = json.loads(data)
        except ValueError:
            raise HTTPException(400, "Invalid JSON") from None
        if not isinstance(value, dict): raise HTTPException(400, "Expected a JSON object")
        if config_read.section("luna", "setup", "memory", default="enabled") != "enabled":
            raise HTTPException(503, "Memory is disabled in Setup")
        return value
    @app.post("/v1/embeddings")
    async def embeddings(request: Request):
        value = await body(request)
        async with slots:
            try: return await asyncio.to_thread(local.response, value)
            except ValueError as exc: raise HTTPException(400, str(exc)) from None
    @app.post("/v1/chat/completions")
    async def reasoning(request: Request):
        value = await body(request)
        async with slots:
            try: return await asyncio.to_thread(complete, value)
            except ValueError as exc: raise HTTPException(422, str(exc)) from None
            except Exception:
                # Provider exceptions can contain URLs/credentials. Never relay their raw text.
                raise HTTPException(503, "The selected memory model is unavailable. Retry or choose another model in Setup.") from None
    return app


def main():
    import argparse
    import uuid
    import uvicorn
    from luna_core.runtime import home
    from hermes_cli.product_runtime import code_root
    import psutil
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nonce", required=True)
    args = parser.parse_args()
    directory = home() / "honcho"
    token = (directory / ".bridge-key").read_text().strip()
    sock = socket.socket()
    if os.name == "nt":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Authenticated high-entropy credential is mandatory on every interface.
    # Binding loopback would make Docker Desktop's host-gateway route unreachable.
    saved_port = directory / ".bridge-port"
    try:
        preferred = int(saved_port.read_text())
        if not 1024 <= preferred <= 65535: preferred = 0
    except (OSError, ValueError):
        preferred = 0
    try: sock.bind(("0.0.0.0", preferred))
    except OSError:
        sock.bind(("0.0.0.0", 0))
    from luna_core.settings import _replace
    _replace(saved_port, str(sock.getsockname()[1]))
    record = {"format": 1, "pid": os.getpid(), "nonce": args.nonce,
              "home": str(home().resolve()), "port": sock.getsockname()[1], "started": time.time(),
              "process_start": psutil.Process().create_time(), "release": str(code_root(home()).resolve())}
    app = create_app(token, record, directory / ".bridge-ready.json")
    uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False)).run(sockets=[sock])


if __name__ == "__main__":
    main()
