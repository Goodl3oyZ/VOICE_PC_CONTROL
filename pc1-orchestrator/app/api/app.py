"""FastAPI inbound adapter for the phone (doc §2, appendix ก.2).

No `from __future__ import annotations` here: FastAPI must resolve the local `Device`
dependency alias at runtime.
"""
import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from ..adapters.notify import Broadcaster
from ..adapters.sqlite_store import SqliteStore
from ..core.orchestrator import Conflict, NotFound, Orchestrator

log = logging.getLogger("pc1.api")
MAX_AUDIO_BYTES = 10 * 1024 * 1024
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
    "Content-Security-Policy": ("default-src 'self'; connect-src 'self' ws: wss:; media-src 'self' blob:; "
                                "img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                "frame-ancestors 'none'; base-uri 'none'"),
}


class CommandIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ConfirmIn(BaseModel):
    approve: bool
    args_hash: str = Field(max_length=100)


def create_app(orch: Orchestrator, store: SqliteStore, broadcaster: Broadcaster,
               static_dir: str | Path | None = None, heartbeat_interval: float | None = None) -> FastAPI:

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = None
        if heartbeat_interval:
            async def beat() -> None:
                while True:
                    await orch.heartbeat()
                    await asyncio.sleep(heartbeat_interval)
            task = asyncio.create_task(beat())
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Voice PC Control — PC1 Orchestrator", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    @app.exception_handler(Conflict)
    async def _conflict(_: Request, e: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=409)

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, e: NotFound) -> JSONResponse:
        return JSONResponse({"detail": "job not found"}, status_code=404)

    def device(request: Request) -> str:
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        name = store.check_token(token.strip()) if scheme.lower() == "bearer" else None
        if name is None:
            raise HTTPException(401, "invalid or missing token", headers={"WWW-Authenticate": "Bearer"})
        return name

    Device = Annotated[str, Depends(device)]

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True}

    @app.post("/command", status_code=202)
    async def command(body: CommandIn, dev: Device) -> dict[str, Any]:
        try:
            job = await orch.submit_text(body.text, dev)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return job.public()

    @app.post("/command/audio", status_code=202)
    async def command_audio(dev: Device, audio: UploadFile = File(...)) -> dict[str, Any]:
        ctype = (audio.content_type or "").split(";")[0]
        if not (ctype.startswith("audio/") or ctype in ("video/webm", "application/octet-stream")):
            raise HTTPException(415, "audio required")
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio too large")
        if not data:
            raise HTTPException(422, "empty audio")
        job = await orch.submit_audio(data, ctype, dev)
        return job.public()

    @app.get("/jobs")
    async def jobs(_: Device, limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
        out = []
        for d in orch.list_jobs(limit):
            d.pop("history", None)
            out.append(d)
        return out

    @app.get("/jobs/{job_id}")
    async def job(job_id: str, _: Device) -> dict[str, Any]:
        return orch.get_job(job_id).public()

    @app.post("/jobs/{job_id}/reply")
    async def reply(job_id: str, body: ReplyIn, dev: Device) -> dict[str, Any]:
        try:
            return (await orch.reply(job_id, body.text, dev)).public()
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.post("/confirm/{job_id}")
    async def confirm(job_id: str, body: ConfirmIn, dev: Device) -> dict[str, Any]:
        return (await orch.confirm(job_id, body.approve, body.args_hash, dev)).public()

    @app.post("/stop")
    async def stop(dev: Device) -> dict[str, Any]:
        return await orch.stop(dev)

    @app.get("/status")
    async def status(_: Device) -> dict[str, Any]:
        return {"pc2_online": orch.pc2_online, "pc2_last_seen": orch.pc2_last_seen,
                "pc2": orch.pc2_status, "heartbeat": bool(heartbeat_interval)}

    @app.websocket("/events")
    async def events(ws: WebSocket, token: str = "") -> None:
        # Browsers can't set headers on WebSocket, so the token comes as a query param (HTTPS/VPN only).
        if store.check_token(token) is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        q = broadcaster.subscribe()
        try:
            await ws.send_json({"type": "pc2.status", "online": orch.pc2_online, "status": orch.pc2_status})
            while True:
                await ws.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            broadcaster.unsubscribe(q)

    if static_dir and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="pwa")

    return app
