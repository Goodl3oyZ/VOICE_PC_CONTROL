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
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from ..adapters.agent_hub import AgentHub
from ..adapters.notify import Broadcaster
from ..adapters.sqlite_store import SqliteStore
from ..core.audit_export import export_audit
from ..core.capabilities import capabilities
from ..core.flows import FlowError
from ..core.orchestrator import Conflict, NotFound, Orchestrator
from .webauth import WebAuth

log = logging.getLogger("pc1.api")
MAX_AUDIO_BYTES = 10 * 1024 * 1024
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
    "Content-Security-Policy": ("default-src 'self'; connect-src 'self' ws: wss:; media-src 'self' blob:; "
                                "img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                "font-src 'self' https://fonts.gstatic.com; form-action 'self'; "
                                "frame-ancestors 'none'; base-uri 'none'"),
}


class CommandIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


FlowAnswer = Annotated[str, Field(max_length=300)]


class FlowRunIn(BaseModel):
    answers: dict[Annotated[str, Field(max_length=40)], FlowAnswer] = Field(default_factory=dict, max_length=10)


class FlowControlIn(FlowRunIn):
    index: int = Field(ge=0, lt=20)


class FlowFollowUpIn(FlowRunIn):
    text: str = Field(min_length=1, max_length=2000)


class ConfirmIn(BaseModel):
    approve: bool
    args_hash: str = Field(max_length=100)


def create_app(orch: Orchestrator, store: SqliteStore, broadcaster: Broadcaster,
               static_dir: str | Path | None = None, heartbeat_interval: float | None = None,
               webauth: WebAuth | None = None, hub: AgentHub | None = None,
               allow_bearer: bool = True) -> FastAPI:
    """allow_bearer: device tokens in an Authorization header (CLI/tests). Disable in public deployments,
    so the browser path (Google session + paired-device cookie) is the only way in."""

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await orch.recover()  # close jobs a previous run left unfinished (they can never complete)
        warm = getattr(orch.llm, "warm", None)
        warm_task = asyncio.create_task(warm()) if warm else None  # load the model now, not on the first command
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
        if warm_task:
            warm_task.cancel()

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
        name = None
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if allow_bearer and scheme.lower() == "bearer":
            name = store.check_token(token.strip())
        elif webauth is not None:
            name = webauth.authorize(request, mutating=request.method not in ("GET", "HEAD"))
        if name is None:
            raise HTTPException(401, "not authorised")
        return name

    Device = Annotated[str, Depends(device)]

    if webauth is not None:
        app.include_router(webauth.router())

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

    @app.post("/command/wake")
    async def command_wake(dev: Device, audio: UploadFile = File(...),
                           armed: bool = Query(False)) -> dict[str, Any]:
        """Hands-free segment (Phase 4): returns ignored | listening | busy | job (no job for ignored speech)."""
        ctype = (audio.content_type or "").split(";")[0].strip().lower()
        if not ctype.startswith("audio/"):
            raise HTTPException(415, "audio required")
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio too large")
        if not data:
            raise HTTPException(422, "empty audio")
        return await orch.submit_wake_audio(data, ctype, dev, armed)

    async def _read_audio(audio: UploadFile) -> tuple[bytes, str]:
        ctype = (audio.content_type or "").split(";")[0].strip().lower()
        if not ctype.startswith("audio/"):
            raise HTTPException(415, "audio required")
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio too large")
        if not data:
            raise HTTPException(422, "empty audio")
        return data, ctype

    @app.get("/flows")
    async def flows(_: Device) -> list[dict[str, Any]]:
        return orch.flows()

    @app.post("/flows/{flow_id}/run")
    async def run_flow(flow_id: str, body: FlowRunIn, dev: Device) -> dict[str, Any]:
        try:
            job = await orch.run_flow(flow_id, body.answers, dev)
        except FlowError as e:
            raise HTTPException(422, str(e)) from e
        return {"job": job.public() if job else None}

    @app.post("/flows/{flow_id}/control")
    async def flow_control(flow_id: str, body: FlowControlIn, dev: Device) -> dict[str, Any]:
        try:
            return (await orch.run_flow_control(flow_id, body.index, body.answers, dev)).public()
        except FlowError as e:
            raise HTTPException(422, str(e)) from e

    @app.post("/flows/{flow_id}/followup")
    async def flow_followup(flow_id: str, body: FlowFollowUpIn, dev: Device) -> dict[str, Any]:
        try:
            return (await orch.run_flow_followup(flow_id, body.text, body.answers, dev)).public()
        except FlowError as e:
            raise HTTPException(422, str(e)) from e

    @app.post("/stt")
    async def stt(_: Device, audio: UploadFile = File(...)) -> dict[str, str]:
        """Voice answer for a wizard stage: returns the text only (no job, not stored)."""
        data, ctype = await _read_audio(audio)
        try:
            return {"text": await orch.transcribe(data, ctype)}
        except TimeoutError as e:
            raise HTTPException(504, "speech recognition took too long") from e

    @app.get("/jobs")
    async def jobs(_: Device, limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
        out = []
        for d in orch.list_jobs(limit):
            d.pop("history", None)
            out.append(d)
        return out

    @app.get("/audit/export")
    async def audit_export(_: Device, fmt: str = Query("jsonl", alias="format", pattern="^(jsonl|csv)$"),
                           days: int = Query(30, ge=1, le=3650)) -> Response:
        """Download the audit log (US-704); the trailer says whether the hash chain verified."""
        import time

        rows, ok = await asyncio.to_thread(lambda: (store.audit_rows(), store.verify_audit()))
        text = export_audit(rows, ok, time.time() - days * 86400, fmt)
        name = time.strftime("voicepc-audit-%Y%m%d") + "." + fmt
        return Response(text, media_type="text/csv" if fmt == "csv" else "application/x-ndjson",
                        headers={"Content-Disposition": f'attachment; filename="{name}"',
                                 "Cache-Control": "no-store"})

    @app.get("/jobs/{job_id}")
    async def job(job_id: str, _: Device) -> dict[str, Any]:
        return orch.get_job(job_id).public()

    @app.post("/jobs/{job_id}/reply")
    async def reply(job_id: str, body: ReplyIn, dev: Device) -> dict[str, Any]:
        try:
            return (await orch.reply(job_id, body.text, dev)).public()
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.get("/capabilities")
    async def capabilities_(_: Device) -> dict[str, Any]:
        return capabilities(orch.kb, orch.cfg.language)

    @app.post("/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, dev: Device) -> dict[str, Any]:
        return (await orch.cancel(job_id, dev)).public()

    @app.post("/confirm/{job_id}")
    async def confirm(job_id: str, body: ConfirmIn, dev: Device) -> dict[str, Any]:
        return (await orch.confirm(job_id, body.approve, body.args_hash, dev)).public()

    @app.post("/stop")
    async def stop(dev: Device) -> dict[str, Any]:
        return await orch.stop(dev)

    @app.get("/status")
    async def status(_: Device) -> dict[str, Any]:
        return {"pc2_online": orch.pc2_online, "pc2_last_seen": orch.pc2_last_seen,
                "pc2": orch.pc2_status, "heartbeat": bool(heartbeat_interval),
                "agent_connected": hub.connected if hub else None}

    @app.websocket("/events")
    async def events(ws: WebSocket, token: str = "") -> None:
        # Browser: session + device cookies (Origin checked). CLI/tests: ?token= when bearer is allowed.
        ok = (allow_bearer and token and store.check_token(token)) or \
            (webauth is not None and webauth.authorize_ws(ws.headers, ws.cookies))
        if not ok:
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

    @app.websocket("/agent/ws")
    async def agent_ws(ws: WebSocket) -> None:
        # PC2 dials out to here; authenticated by an HMAC challenge inside AgentHub, not by cookies.
        if hub is None:
            await ws.close(code=4404)
            return
        await hub.attach(ws)

    if static_dir and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="pwa")

    return app
