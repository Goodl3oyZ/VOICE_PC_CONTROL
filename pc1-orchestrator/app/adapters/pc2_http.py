"""PC1 -> PC2 client: HMAC-signed HTTPS calls with idempotency keys (doc §14.4(d), §14.7)."""
from __future__ import annotations

import json
from typing import Any

import httpx

from voice_contracts.models import ToolResult
from voice_contracts.signing import signed_headers

from ..ports import PC2Unavailable


class PC2HttpTools:
    def __init__(self, base_url: str, secret: bytes, timeout: float = 15.0,
                 verify: bool | str = True, client: httpx.AsyncClient | None = None):
        self._secret = secret
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout, verify=verify)

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None,
                       idempotency_key: str | None = None,
                       extra_headers: dict[str, str] | None = None) -> ToolResult:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        headers = signed_headers(self._secret, method, path, body, idempotency_key=idempotency_key)
        headers["Content-Type"] = "application/json"
        headers.update(extra_headers or {})
        try:
            r = await self._client.request(method, path, content=body, headers=headers)
        except httpx.HTTPError as e:
            raise PC2Unavailable(type(e).__name__) from e
        if r.status_code in (401, 403):
            return ToolResult(ok=False, error=f"PC2 ปฏิเสธคำขอ ({r.status_code})")
        if r.status_code >= 500:
            raise PC2Unavailable(f"HTTP {r.status_code}")
        try:
            return ToolResult.model_validate(r.json())
        except ValueError:
            return ToolResult(ok=False, error=f"PC2 ตอบกลับผิดรูปแบบ (HTTP {r.status_code})")

    async def call(self, tool: str, arguments: dict[str, Any], idempotency_key: str,
                   approved_hash: str | None = None) -> ToolResult:
        extra = {"X-Approved-Args-Hash": approved_hash} if approved_hash else None
        return await self._request("POST", f"/tool/{tool}", arguments, idempotency_key, extra)

    async def stop_all(self) -> ToolResult:
        return await self._request("POST", "/stop", {})

    async def status(self) -> ToolResult:
        return await self._request("GET", "/status")
