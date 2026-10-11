"""Web login for the public PWA: Google OAuth (allowlisted emails) + one-time Secret Key per device.

A request is authorised only when BOTH hold (defense in depth, doc §20.4 layers 2–3):
  1. `vpc_session` cookie — signed, short-lived, proves a Google login by an allowed email;
  2. `vpc_device`  cookie — a revocable device token, issued once the Secret Key was entered on that device.
Cookies are HttpOnly (JS can't read them), Secure, SameSite=Lax. State-changing requests additionally need
the `X-Requested-With: voicepc` header, which a cross-site page cannot send without a CORS preflight (CSRF).
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ..adapters.sqlite_store import SqliteStore

log = logging.getLogger("pc1.webauth")
SESSION_COOKIE, DEVICE_COOKIE, STATE_COOKIE = "vpc_session", "vpc_device", "vpc_oauth"
CSRF_HEADER, CSRF_VALUE = "x-requested-with", "voicepc"
PAIRING_KEY_SETTING = "pairing_key_sha256"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
# A URL, not a secret
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"  # noqa: S105  # nosec B105
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


@dataclass
class WebAuthConfig:
    public_url: str  # e.g. https://pc.flukelnwza.online (used for redirect URI + cookie Secure flag)
    session_secret: bytes
    google_client_id: str = ""
    google_client_secret: str = ""
    allowed_emails: set[str] = field(default_factory=set)
    session_ttl_s: int = 7 * 24 * 3600
    device_ttl_s: int = 180 * 24 * 3600
    max_pair_failures: int = 5
    pair_window_s: int = 15 * 60

    @property
    def secure(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def origin(self) -> str:
        return self.public_url.rstrip("/")

    @property
    def redirect_uri(self) -> str:
        return self.origin + "/auth/google/callback"


def hash_key(key: str) -> str:
    """Normalised so the user may type it with/without dashes, spaces or lowercase."""
    norm = "".join(ch for ch in key.upper() if ch.isalnum())
    return hashlib.sha256(norm.encode()).hexdigest()


def new_pairing_key() -> str:
    """Human-typable random key, ~100 bits: e.g. 7QF2-9XMB-K4DT-PZ8W-3NHC."""
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I
    raw = "".join(secrets.choice(alphabet) for _ in range(20))
    return "-".join(raw[i:i + 4] for i in range(0, 20, 4))


class Signer:
    def __init__(self, secret: bytes):
        self._secret = secret

    def dumps(self, data: dict[str, Any]) -> str:
        body = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")
        sig = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{sig}"

    def loads(self, token: str | None) -> dict[str, Any] | None:
        if not token or "." not in token or len(token) > 4096:
            return None
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest(), sig):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("exp", 0) < time.time():
            return None
        return data


class PairLimiter:
    """At most N wrong Secret Keys per (email, ip) per window — brute force protection."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self._fails: dict[str, list[float]] = {}

    def blocked(self, key: str) -> bool:
        now = time.time()
        recent = [t for t in self._fails.get(key, []) if now - t < self.window]
        self._fails[key] = recent
        return len(recent) >= self.limit

    def fail(self, key: str) -> None:
        self._fails.setdefault(key, []).append(time.time())


class PairIn(BaseModel):
    key: str = Field(min_length=4, max_length=100)
    label: str = Field(default="device", max_length=40)


def client_ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")


class WebAuth:
    def __init__(self, cfg: WebAuthConfig, store: SqliteStore, http: httpx.AsyncClient | None = None):
        self.cfg, self.store = cfg, store
        self.signer = Signer(cfg.session_secret)
        self.http = http or httpx.AsyncClient(timeout=15)
        self.limiter = PairLimiter(cfg.max_pair_failures, cfg.pair_window_s)

    # ------------------------------------------------------------ checks used by the API
    def session_email(self, request: Request) -> str | None:
        data = self.signer.loads(request.cookies.get(SESSION_COOKIE))
        email = (data or {}).get("email", "")
        return email if email and email.lower() in self.cfg.allowed_emails else None

    def device_name(self, request: Request) -> str | None:
        return self.store.check_token(request.cookies.get(DEVICE_COOKIE, ""))

    def authorize(self, request: Request, mutating: bool) -> str | None:
        """Return the device name if session + device + CSRF checks pass, else None."""
        if not self.session_email(request):
            return None
        if mutating and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return None
        return self.device_name(request)

    def authorize_ws(self, ws_headers: Any, cookies: dict[str, str]) -> str | None:
        if ws_headers.get("origin", "").rstrip("/") != self.cfg.origin:  # cross-site WebSocket hijacking
            return None
        data = self.signer.loads(cookies.get(SESSION_COOKIE))
        if not data or data.get("email", "").lower() not in self.cfg.allowed_emails:
            return None
        return self.store.check_token(cookies.get(DEVICE_COOKIE, ""))

    def _set_cookie(self, resp: Any, name: str, value: str, max_age: int) -> None:
        resp.set_cookie(name, value, max_age=max_age, httponly=True, secure=self.cfg.secure,
                        samesite="lax", path="/")

    # ------------------------------------------------------------ routes
    def router(self) -> APIRouter:
        r = APIRouter(prefix="/auth")

        @r.get("/me")
        async def me(request: Request) -> dict[str, Any]:
            email = self.session_email(request)
            return {"authenticated": bool(email), "email": email,
                    "paired": bool(email and self.device_name(request)),
                    "google_enabled": bool(self.cfg.google_client_id)}

        @r.get("/google/login")
        async def google_login() -> RedirectResponse:
            if not self.cfg.google_client_id:
                raise HTTPException(503, "Google login is not configured")
            state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            q = {"client_id": self.cfg.google_client_id, "redirect_uri": self.cfg.redirect_uri,
                 "response_type": "code", "scope": "openid email profile", "state": state,
                 "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"}
            resp = RedirectResponse(GOOGLE_AUTH + "?" + urlencode(q), status_code=302)
            self._set_cookie(resp, STATE_COOKIE,
                             self.signer.dumps({"s": state, "v": verifier, "exp": time.time() + 600}), 600)
            return resp

        @r.get("/google/callback")
        async def google_callback(request: Request, code: str = "", state: str = "",
                                  error: str = "") -> RedirectResponse:
            def fail(reason: str) -> RedirectResponse:
                log.warning("google login failed: %s", reason)
                resp = RedirectResponse("/?auth_error=" + reason, status_code=302)
                resp.delete_cookie(STATE_COOKIE, path="/")
                return resp

            saved = self.signer.loads(request.cookies.get(STATE_COOKIE))
            if error:
                return fail("denied")
            if not saved or not code or not hmac.compare_digest(saved.get("s", ""), state):
                return fail("state")
            try:
                tok = await self.http.post(GOOGLE_TOKEN, data={
                    "client_id": self.cfg.google_client_id, "client_secret": self.cfg.google_client_secret,
                    "code": code, "code_verifier": saved["v"], "grant_type": "authorization_code",
                    "redirect_uri": self.cfg.redirect_uri})
                tok.raise_for_status()
                info = await self.http.get(GOOGLE_USERINFO,
                                           headers={"Authorization": f"Bearer {tok.json()['access_token']}"})
                info.raise_for_status()
                user = info.json()
            except (httpx.HTTPError, KeyError, ValueError) as e:
                return fail(f"google_{type(e).__name__}")
            email = (user.get("email") or "").lower()
            if not user.get("email_verified") or email not in self.cfg.allowed_emails:
                self.store.append_audit("login_denied", None, {"email": email, "ip": client_ip(request)})
                return fail("not_allowed")
            self.store.append_audit("login", None, {"email": email, "ip": client_ip(request)})
            resp = RedirectResponse("/", status_code=302)
            resp.delete_cookie(STATE_COOKIE, path="/")
            self._set_cookie(resp, SESSION_COOKIE,
                             self.signer.dumps({"email": email, "exp": time.time() + self.cfg.session_ttl_s}),
                             self.cfg.session_ttl_s)
            return resp

        @r.post("/pair")
        async def pair(body: PairIn, request: Request) -> JSONResponse:
            email = self.session_email(request)
            if not email or request.headers.get(CSRF_HEADER) != CSRF_VALUE:
                raise HTTPException(401, "sign in with Google first")
            who = f"{email}|{client_ip(request)}"
            if self.limiter.blocked(who):
                raise HTTPException(429, "too many wrong keys, try again in 15 minutes")
            stored = self.store.get_setting(PAIRING_KEY_SETTING)
            if not stored or not hmac.compare_digest(stored, hash_key(body.key)):
                self.limiter.fail(who)
                self.store.append_audit("pair_failed", None, {"email": email, "ip": client_ip(request)})
                raise HTTPException(403, "wrong secret key")
            label = "".join(c for c in body.label if c.isalnum() or c in "-_ ")[:40] or "device"
            name = f"{email}:{label}:{secrets.token_hex(3)}"
            token = self.store.create_device(name)
            self.store.append_audit("pair", None, {"email": email, "device": name, "ip": client_ip(request)})
            resp = JSONResponse({"paired": True, "device": name})
            self._set_cookie(resp, DEVICE_COOKIE, token, self.cfg.device_ttl_s)
            return resp

        @r.post("/logout")
        async def logout(request: Request) -> JSONResponse:
            if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
                raise HTTPException(403, "missing csrf header")
            resp = JSONResponse({"ok": True})
            resp.delete_cookie(SESSION_COOKIE, path="/")  # device stays paired: no Secret Key next time
            return resp

        @r.post("/unpair")
        async def unpair(request: Request) -> JSONResponse:
            dev = self.authorize(request, mutating=True)
            if not dev:
                raise HTTPException(401, "not authorised")
            self.store.revoke_device(dev)
            self.store.append_audit("unpair", None, {"device": dev})
            resp = JSONResponse({"ok": True})
            resp.delete_cookie(DEVICE_COOKIE, path="/")
            resp.delete_cookie(SESSION_COOKIE, path="/")
            return resp

        return r
