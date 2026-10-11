"""Reverse connection to PC2: the Windows agent dials OUT to PC1 over a WebSocket (through Cloudflare),
so the notebook needs no VPN and no open port.

Handshake: PC1 sends a random challenge; the agent answers HMAC(secret, "agent-hello|challenge|agent_nonce").
After that, PC1 relays HTTP-shaped requests that are *still individually HMAC-signed* (voice_contracts.signing),
so the agent verifies every command exactly as before — a fake server can't forge commands either.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from ..ports import PC2Unavailable
from .pc2_http import PC2HttpTools

log = logging.getLogger("pc1.agent_hub")
HELLO_TIMEOUT_S = 10


def hello_signature(secret: bytes, challenge: str, agent_nonce: str) -> str:
    return hmac.new(secret, f"agent-hello|{challenge}|{agent_nonce}".encode(), hashlib.sha256).hexdigest()


class AgentHub:
    def __init__(self, secret: bytes):
        self._secret = secret
        self._ws: WebSocket | None = None
        self._pending: dict[str, asyncio.Future[tuple[int, str]]] = {}
        self._send_lock = asyncio.Lock()
        self.connected_since: float | None = None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def attach(self, ws: WebSocket) -> None:
        """Serve one agent connection until it closes. A newer authenticated connection replaces an older one."""
        await ws.accept()
        challenge = secrets.token_hex(16)
        await ws.send_json({"type": "challenge", "nonce": challenge})
        try:
            hello = await asyncio.wait_for(ws.receive_json(), HELLO_TIMEOUT_S)
        except (TimeoutError, WebSocketDisconnect, ValueError, KeyError):
            await self._close(ws, 4401)
            return
        expected = hello_signature(self._secret, challenge, str(hello.get("nonce", ""))[:128])
        if hello.get("type") != "hello" or not hmac.compare_digest(expected, str(hello.get("sig", ""))):
            log.warning("agent handshake rejected")
            await self._close(ws, 4401)
            return
        old, self._ws = self._ws, ws
        if old is not None:
            await self._close(old, 4000)
        self.connected_since = asyncio.get_running_loop().time()
        log.info("agent connected")
        await ws.send_json({"type": "welcome"})
        try:
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "response":
                    fut = self._pending.pop(str(msg.get("id")), None)
                    if fut and not fut.done():
                        fut.set_result((int(msg.get("status", 502)), str(msg.get("body", ""))))
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass
        finally:
            if self._ws is ws:
                self._ws = None
                self.connected_since = None
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(PC2Unavailable("agent disconnected"))
                self._pending.clear()
                log.info("agent disconnected")

    async def request(self, method: str, path: str, headers: dict[str, str], body: bytes,
                      timeout: float) -> tuple[int, str]:
        ws = self._ws
        if ws is None:
            raise PC2Unavailable("agent not connected")
        rid = secrets.token_hex(8)
        fut: asyncio.Future[tuple[int, str]] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            async with self._send_lock:
                await ws.send_text(json.dumps({"type": "request", "id": rid, "method": method, "path": path,
                                               "headers": headers, "body": body.decode("utf-8")}))
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError as e:
            raise PC2Unavailable("agent did not answer in time") from e
        except (RuntimeError, WebSocketDisconnect) as e:
            raise PC2Unavailable("agent connection lost") from e
        finally:
            self._pending.pop(rid, None)

    @staticmethod
    async def _close(ws: WebSocket, code: int) -> None:
        try:
            await ws.close(code=code)
        except RuntimeError:
            pass


class PC2RelayTools(PC2HttpTools):
    """Same signed requests as PC2HttpTools, carried over the agent's WebSocket instead of HTTP."""

    def __init__(self, hub: AgentHub, secret: bytes, timeout: float = 15.0):
        self._hub, self._timeout = hub, timeout
        self._secret = secret

    async def _send(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, Any]:
        status, text = await self._hub.request(method, path, headers, body, self._timeout)
        try:
            return status, json.loads(text)
        except ValueError:
            return status, None
