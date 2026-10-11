"""Public web access: Google OAuth (mocked) + Secret Key device pairing + CSRF + WebSocket origin checks."""
from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.notify import Broadcaster
from app.api.app import create_app
from app.api.webauth import (
    PAIRING_KEY_SETTING,
    SESSION_COOKIE,
    Signer,
    WebAuth,
    WebAuthConfig,
    hash_key,
    new_pairing_key,
)

ORIGIN = "http://testserver"
KEY = "7QF2-9XMB-K4DT-PZ8W-3NHC"
CSRF = {"X-Requested-With": "voicepc"}


def google_mock(email: str = "owner@gmail.com", verified: bool = True):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com":
            seen["token_form"] = parse_qs(req.content.decode())
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer"})
        if req.url.host == "openidconnect.googleapis.com":
            return httpx.Response(200, json={"email": email, "email_verified": verified})
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


@pytest.fixture
def web(rig):
    def make(email="owner@gmail.com", verified=True, allow_bearer=False):
        http, seen = google_mock(email, verified)
        cfg = WebAuthConfig(public_url=ORIGIN, session_secret=b"s" * 40, google_client_id="cid",
                            google_client_secret="csecret", allowed_emails={"owner@gmail.com"})
        wa = WebAuth(cfg, rig.store, http=http)
        rig.store.set_setting(PAIRING_KEY_SETTING, hash_key(KEY))
        bus = Broadcaster()
        rig.orch.notify = bus
        client = TestClient(create_app(rig.orch, rig.store, bus, webauth=wa, allow_bearer=allow_bearer),
                            follow_redirects=False)
        return client, seen
    return make


def login(client) -> httpx.Response:
    r = client.get("/auth/google/login")
    assert r.status_code == 302
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return client.get("/auth/google/callback", params={"code": "c0de", "state": q["state"][0]})


def test_me_when_anonymous(web):
    client, _ = web()
    assert client.get("/auth/me").json() == {"authenticated": False, "email": None, "paired": False,
                                             "google_enabled": True}


def test_google_login_uses_pkce_and_state(web):
    client, seen = web()
    r = client.get("/auth/google/login")
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert q["redirect_uri"] == [ORIGIN + "/auth/google/callback"]
    assert q["code_challenge_method"] == ["S256"] and q["state"][0]
    assert "httponly" in r.headers["set-cookie"].lower()
    r = client.get("/auth/google/callback", params={"code": "c0de", "state": q["state"][0]})
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert seen["token_form"]["code_verifier"][0] and seen["token_form"]["client_secret"] == ["csecret"]
    me = client.get("/auth/me").json()
    assert me["authenticated"] and me["email"] == "owner@gmail.com" and not me["paired"]


@pytest.mark.security
def test_callback_rejects_wrong_state(web):
    client, _ = web()
    client.get("/auth/google/login")
    r = client.get("/auth/google/callback", params={"code": "c0de", "state": "forged"})
    assert "auth_error=state" in r.headers["location"]
    assert not client.get("/auth/me").json()["authenticated"]


@pytest.mark.security
@pytest.mark.parametrize("email,verified", [("attacker@gmail.com", True), ("owner@gmail.com", False)])
def test_not_allowed_or_unverified_email_denied(web, rig, email, verified):
    client, _ = web(email=email, verified=verified)
    r = login(client)
    assert "auth_error=not_allowed" in r.headers["location"]
    assert not client.get("/auth/me").json()["authenticated"]
    assert any(a["kind"] == "login_denied" for a in rig.store.audit_rows())


@pytest.mark.security
def test_api_needs_session_device_and_csrf(web):
    client, _ = web()
    assert client.post("/command", json={"text": "เปิดโน้ตแพด"}, headers=CSRF).status_code == 401  # nothing
    login(client)
    assert client.post("/command", json={"text": "เปิดโน้ตแพด"}, headers=CSRF).status_code == 401  # no device
    assert client.post("/auth/pair", json={"key": KEY}, headers=CSRF).json()["paired"]
    assert client.get("/auth/me").json()["paired"]
    assert client.post("/command", json={"text": "เปิดโน้ตแพด"}).status_code == 401  # no CSRF header
    assert client.post("/command", json={"text": "เปิดโน้ตแพด"}, headers=CSRF).status_code == 202
    assert client.get("/status").status_code == 200  # GET needs no CSRF header


@pytest.mark.security
def test_pair_needs_google_first(web):
    client, _ = web()
    assert client.post("/auth/pair", json={"key": KEY}, headers=CSRF).status_code == 401


@pytest.mark.security
def test_wrong_key_rate_limited(web):
    client, _ = web()
    login(client)
    for _ in range(5):
        assert client.post("/auth/pair", json={"key": "AAAA-BBBB"}, headers=CSRF).status_code == 403
    assert client.post("/auth/pair", json={"key": KEY}, headers=CSRF).status_code == 429  # even the right one


def test_key_is_forgiving_about_format(web):
    client, _ = web()
    login(client)
    assert client.post("/auth/pair", json={"key": KEY.lower().replace("-", " ")}, headers=CSRF).status_code == 200


@pytest.mark.security
def test_bearer_disabled_in_public_mode(web, rig):
    client, _ = web(allow_bearer=False)
    token = rig.store.create_device("cli")
    assert client.get("/status", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_logout_keeps_device_unpair_revokes(web, rig):
    client, _ = web()
    login(client)
    client.post("/auth/pair", json={"key": KEY}, headers=CSRF)
    assert client.post("/auth/logout", headers=CSRF).json()["ok"]
    assert not client.get("/auth/me").json()["authenticated"]
    login(client)
    assert client.get("/auth/me").json()["paired"]  # no Secret Key needed again on this device
    assert client.post("/auth/unpair", headers=CSRF).json()["ok"]
    login(client)
    assert not client.get("/auth/me").json()["paired"]


@pytest.mark.security
def test_websocket_checks_origin_and_cookies(web):
    client, _ = web()
    login(client)
    client.post("/auth/pair", json={"key": KEY}, headers=CSRF)
    with client.websocket_connect("/events", headers={"Origin": ORIGIN}) as ws:
        assert ws.receive_json()["type"] == "pc2.status"
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
            "/events", headers={"Origin": "https://evil.example"}) as ws:
        ws.receive_json()


@pytest.mark.security
def test_session_cookie_tamper_and_expiry():
    s = Signer(b"k" * 40)
    tok = s.dumps({"email": "owner@gmail.com", "exp": time.time() + 60})
    assert s.loads(tok)["email"] == "owner@gmail.com"
    body, sig = tok.rsplit(".", 1)
    assert s.loads(body + "." + "0" * len(sig)) is None
    assert s.loads(s.dumps({"email": "x", "exp": time.time() - 1})) is None
    assert Signer(b"other" * 10).loads(tok) is None


def test_session_cookie_name_not_readable_by_js(web):
    client, _ = web()
    r = login(client)
    cookie = [c for c in r.headers.get_list("set-cookie") if c.startswith(SESSION_COOKIE)][0].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_pairing_key_format():
    k = new_pairing_key()
    assert len(k) == 24 and k.count("-") == 4 and not set(k) & set("01OI")
