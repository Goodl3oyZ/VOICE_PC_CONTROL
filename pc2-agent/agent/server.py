"""PC2 Agent API (doc ch.2 figure PC2, §14.2 steps 7–9).

Every request: client IP allowlist -> HMAC signature + timestamp + one-time nonce ->
idempotency cache -> policy re-check -> audit (fail closed) -> run tool -> verify -> audit.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from voice_contracts.models import ToolResult
from voice_contracts.signing import NonceCache, verify

from .audit import AuditLog
from .config import AgentConfig
from .launcher import Launcher
from .policy import AgentPolicy, KillSwitch
from .tools import REGISTRY, ToolContext
from .tools.status import status_data

log = logging.getLogger("pc2.agent")
IDEMPOTENCY_TTL_S = 600


def create_app(cfg: AgentConfig, secret: bytes, launcher: Launcher,
               clock: Callable[[], float] = time.time,
               sleep: Callable[[float], None] = time.sleep) -> FastAPI:
    if len(secret) < 32:
        raise ValueError("agent secret must be at least 32 bytes")
    data_dir = Path(cfg.data_dir)
    kill = KillSwitch(data_dir / "killswitch.flag")
    policy = AgentPolicy(cfg, kill, clock)
    audit = AuditLog(data_dir / "audit.jsonl")
    nonces = NonceCache()
    idem: dict[str, tuple[float, dict[str, Any]]] = {}
    ctx = ToolContext(cfg=cfg, launcher=launcher, kill=kill, sleep=sleep)
    run_lock = asyncio.Lock()

    app = FastAPI(title="Voice PC Control — PC2 Agent", version="0.1.0",
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.kill = kill
    app.state.audit = audit
    app.state.ctx = ctx

    async def authenticate(request: Request) -> bytes:
        client = request.client.host if request.client else ""
        if cfg.allowed_clients and client not in cfg.allowed_clients:
            raise HTTPException(403, "client not allowed")
        body = await request.body()
        reason = verify(secret, request.method, request.url.path, request.headers, body, nonces, clock())
        if reason:
            try:
                audit.append("auth_fail", {"client": client, "path": request.url.path, "reason": reason})
            except OSError:
                pass
            raise HTTPException(401, reason)
        return body

    def _audit_or_503(kind: str, data: dict[str, Any]) -> None:
        try:
            audit.append(kind, data)
        except OSError as e:
            log.error("audit write failed: %s", e)
            raise HTTPException(503, "audit unavailable (fail closed)") from e

    async def run_tool(name: str, raw: Any, key: str | None, approved: str | None) -> dict[str, Any]:
        now = clock()
        for k, (t, _) in list(idem.items()):
            if now - t > IDEMPOTENCY_TTL_S:
                del idem[k]
        if key and key in idem:  # retry of a request we already executed (TC-R04)
            return idem[key][1]
        check = policy.check(name, raw, approved)
        _audit_or_503("request", {"tool": name, "args": raw, "key": key, "allowed": check.ok,
                                  "reason": check.reason})
        if not check.ok:
            result = ToolResult(ok=False, error=f"policy deny: {check.reason}")
        elif name == "stop_all":  # must not wait behind the running tool
            result = REGISTRY[name](check.args, ctx)  # type: ignore[arg-type]
        else:
            async with run_lock:
                ctx.cancel.clear()
                t0 = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(REGISTRY[name], check.args, ctx),  # type: ignore[arg-type]
                        cfg.tool_timeout_s)
                except TimeoutError:
                    result = ToolResult(ok=False, error="tool timeout")
                except Exception as e:  # noqa: BLE001 — report, never crash the agent
                    log.exception("tool %s failed", name)
                    result = ToolResult(ok=False, error=f"{type(e).__name__}")
                result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        out = result.model_dump()
        _audit_or_503("result", {"tool": name, "key": key, "ok": result.ok,
                                 "verified": result.verified, "error": result.error})
        if key:
            idem[key] = (now, out)
        return out

    @app.post("/tool/{name}")
    async def tool(name: str, request: Request) -> JSONResponse:
        body = await authenticate(request)
        try:
            raw = json.loads(body or b"{}")
        except ValueError as e:
            raise HTTPException(400, "body must be JSON") from e
        out = await run_tool(name, raw, request.headers.get("x-idempotency-key"),
                             request.headers.get("x-approved-args-hash"))
        return JSONResponse(out)

    @app.post("/stop")
    async def stop(request: Request) -> JSONResponse:
        await authenticate(request)
        return JSONResponse(await run_tool("stop_all", {}, None, None))

    @app.get("/status")
    async def status(request: Request) -> JSONResponse:
        await authenticate(request)
        return JSONResponse(ToolResult(ok=True, verified=True, data=status_data(ctx)).model_dump())

    @app.post("/killswitch")
    async def killswitch(request: Request) -> JSONResponse:
        body = await authenticate(request)
        try:
            on = bool(json.loads(body or b"{}").get("on", True))
        except (ValueError, AttributeError) as e:
            raise HTTPException(400, "body must be {\"on\": bool}") from e
        kill.set(on)
        if on:
            ctx.cancel.set()
        _audit_or_503("killswitch", {"on": on, "via": "api"})
        return JSONResponse({"kill_switch": kill.on})

    return app
