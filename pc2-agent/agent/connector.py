"""Outbound connector: the agent dials PC1 (wss://.../agent/ws) instead of listening on the network.

Every relayed request is replayed into the agent's own FastAPI app in-process, so the existing defenses
still apply unchanged: HMAC signature + timestamp + one-time nonce, idempotency, policy re-check, kill
switch, rate limit and audit log. The notebook opens no inbound port and needs no VPN.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from typing import Any

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

log = logging.getLogger("pc2.connector")


def hello_signature(secret: bytes, challenge: str, agent_nonce: str) -> str:
    return hmac.new(secret, f"agent-hello|{challenge}|{agent_nonce}".encode(), hashlib.sha256).hexdigest()


async def _serve(ws: Any, local: httpx.AsyncClient) -> None:
    async def handle(msg: dict[str, Any]) -> None:
        try:
            r = await local.request(msg["method"], msg["path"], headers=msg.get("headers") or {},
                                    content=(msg.get("body") or "").encode("utf-8"))
            status, body = r.status_code, r.text
        except Exception as e:  # noqa: BLE001 — always answer, never leave PC1 waiting
            log.exception("local request failed")
            status, body = 500, json.dumps({"ok": False, "error": type(e).__name__})
        await ws.send(json.dumps({"type": "response", "id": msg.get("id"), "status": status, "body": body}))

    tasks: set[asyncio.Task[None]] = set()
    async for raw in ws:
        msg = json.loads(raw)
        if msg.get("type") == "request":
            t = asyncio.create_task(handle(msg))  # stop_all must not wait behind a running tool
            tasks.add(t)
            t.add_done_callback(tasks.discard)


async def run_connector(app: Any, url: str, secret: bytes, max_backoff: float = 30.0) -> None:
    """Keep a connection to PC1 open forever, reconnecting with exponential backoff."""
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 0))
    backoff = 1.0
    async with httpx.AsyncClient(transport=transport, base_url="http://agent", timeout=60) as local:
        while True:
            try:
                async with connect(url, open_timeout=15, ping_interval=20, ping_timeout=20,
                                   max_size=2 ** 20, user_agent_header="voice-pc-agent/0.1") as ws:
                    challenge = json.loads(await asyncio.wait_for(ws.recv(), 10))
                    nonce = secrets.token_hex(16)
                    await ws.send(json.dumps({"type": "hello", "agent": "pc2", "nonce": nonce,
                                              "sig": hello_signature(secret, challenge.get("nonce", ""), nonce)}))
                    welcome = json.loads(await asyncio.wait_for(ws.recv(), 10))
                    if welcome.get("type") != "welcome":
                        raise ConnectionError("handshake rejected")
                    log.info("connected to PC1 at %s", url)
                    backoff = 1.0
                    await _serve(ws, local)
            except (OSError, ConnectionClosed, InvalidStatus, TimeoutError, ConnectionError, ValueError) as e:
                log.warning("PC1 connection lost (%s); retrying in %.0fs", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(max_backoff, backoff * 2)
