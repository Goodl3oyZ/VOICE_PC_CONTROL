"""PC1 -> PC2 request signing (doc §14.4(d), §20.6).

signature = HMAC-SHA256(secret, METHOD|PATH|TIMESTAMP|NONCE|sha256(body))
PC2 rejects: bad signature, timestamp outside ±30 s, reused nonce.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Mapping

WINDOW_SECONDS = 30


def _message(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    body_hash = hashlib.sha256(body).hexdigest()
    return "|".join([method.upper(), path, timestamp, nonce, body_hash]).encode()


def sign(secret: bytes, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    return hmac.new(secret, _message(method, path, timestamp, nonce, body), hashlib.sha256).hexdigest()


def signed_headers(secret: bytes, method: str, path: str, body: bytes, device: str = "pc1",
                   idempotency_key: str | None = None, now: float | None = None) -> dict[str, str]:
    ts = str(int(now if now is not None else time.time()))
    nonce = secrets.token_hex(16)
    headers = {
        "X-Device": device,
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Signature": sign(secret, method, path, ts, nonce, body),
    }
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    return headers


class NonceCache:
    """Remembers nonces for the validity window so a captured request can't be replayed."""

    def __init__(self, ttl: float = WINDOW_SECONDS * 2):
        self._ttl = ttl
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def check_and_add(self, nonce: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            for n, t in list(self._seen.items()):
                if now - t > self._ttl:
                    del self._seen[n]
            if nonce in self._seen:
                return False
            self._seen[nonce] = now
            return True


def verify(secret: bytes, method: str, path: str, headers: Mapping[str, str], body: bytes,
           nonces: NonceCache, now: float | None = None) -> str | None:
    """Return None when valid, otherwise a short reason string.

    `headers` must be case-insensitive or lower-cased (Starlette headers are).
    """
    now = now if now is not None else time.time()
    ts, nonce, sig = headers.get("x-timestamp"), headers.get("x-nonce"), headers.get("x-signature")
    if not ts or not nonce or not sig:
        return "missing signature headers"
    try:
        ts_int = int(ts)
    except ValueError:
        return "bad timestamp"
    if abs(now - ts_int) > WINDOW_SECONDS:
        return "timestamp outside window"
    if len(nonce) > 128:
        return "bad nonce"
    expected = sign(secret, method, path, ts, nonce, body)
    if not hmac.compare_digest(expected, sig):
        return "bad signature"
    if not nonces.check_and_add(nonce, now):
        return "replayed nonce"
    return None
