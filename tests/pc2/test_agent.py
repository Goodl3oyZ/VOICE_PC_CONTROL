"""PC2 agent: signing, replay, idempotency, policy re-check, kill switch, tools (TC-S01/S02/S05/S06/S09, TC-R04)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agent.audit import AuditLog
from agent.config import AgentConfig
from agent.launcher import FakeLauncher
from agent.server import create_app
from voice_contracts.signing import NonceCache, sign, signed_headers, verify
from voice_contracts.tools import args_hash

SECRET = b"test-secret-0123456789-abcdefghijklmnop"


@pytest.fixture
def cfg(tmp_path) -> AgentConfig:
    return AgentConfig.from_dict({
        "apps": {"chrome": {"process": "chrome.exe", "argv": ["C:/chrome.exe"]},
                 "notepad": {"process": "notepad.exe", "argv": ["notepad.exe"]},
                 "spotify": {"process": "Spotify.exe", "uri": "spotify:"}},
        "browser_argv": ["C:/chrome.exe"], "browser_process": "chrome.exe",
        "allowed_hosts": ["youtube.com"], "allowed_clients": ["testclient"],
        "rate_limit_per_min": 30, "verify_timeout_s": 0.2, "data_dir": str(tmp_path / "data"),
    })


@pytest.fixture
def launcher() -> FakeLauncher:
    fl = FakeLauncher()
    fl.process_for_argv0 = {"notepad.exe": "notepad.exe", "C:/chrome.exe": "chrome.exe"}
    fl.process_for_uri = {"spotify:": "Spotify.exe"}
    return fl


@pytest.fixture
def agent(cfg, launcher):
    app = create_app(cfg, SECRET, launcher, sleep=lambda s: None)
    with TestClient(app) as c:
        yield c, app


def call(client, path, payload=None, method="POST", key=None, secret=SECRET, headers=None, **kw):
    body = b"" if payload is None else json.dumps(payload).encode()
    h = signed_headers(secret, method, path, body, idempotency_key=key, **kw)
    h.update(headers or {})
    return client.request(method, path, content=body, headers=h)


# ---------------------------------------------------------------- signing primitives
def test_sign_verify_roundtrip():
    body = b'{"a":1}'
    h = {k.lower(): v for k, v in signed_headers(SECRET, "POST", "/tool/x", body, now=1000).items()}
    assert verify(SECRET, "POST", "/tool/x", h, body, NonceCache(), now=1005) is None
    assert verify(SECRET, "POST", "/tool/y", h, body, NonceCache(), now=1005) == "bad signature"
    assert verify(SECRET, "POST", "/tool/x", h, b'{"a":2}', NonceCache(), now=1005) == "bad signature"
    assert verify(SECRET, "POST", "/tool/x", h, body, NonceCache(), now=1031) == "timestamp outside window"


def test_short_secret_rejected(cfg, launcher):
    with pytest.raises(ValueError):
        create_app(cfg, b"short", launcher)


# ---------------------------------------------------------------- auth (TC-S01, TC-S02)
@pytest.mark.security
def test_tc_s01_unsigned_and_wrong_key_rejected(agent, launcher):
    client, _ = agent
    assert client.post("/tool/open_app", json={"app": "notepad"}).status_code == 401
    assert call(client, "/tool/open_app", {"app": "notepad"}, secret=b"x" * 40).status_code == 401
    assert launcher.launched == []


@pytest.mark.security
def test_tc_s01_client_ip_not_allowed(cfg, launcher):
    cfg.allowed_clients = ["10.0.0.5"]
    with TestClient(create_app(cfg, SECRET, launcher)) as c:
        assert call(c, "/tool/open_app", {"app": "notepad"}).status_code == 403


@pytest.mark.security
def test_tc_s02_replay_and_old_timestamp(agent, launcher):
    client, _ = agent
    body = json.dumps({"app": "notepad"}).encode()
    h = signed_headers(SECRET, "POST", "/tool/open_app", body)
    assert client.post("/tool/open_app", content=body, headers=h).status_code == 200
    r = client.post("/tool/open_app", content=body, headers=h)
    assert r.status_code == 401 and r.json()["detail"] == "replayed nonce"
    import time
    old = call(client, "/tool/open_app", {"app": "notepad"}, now=time.time() - 60)
    assert old.status_code == 401
    assert len(launcher.launched) == 1


# ---------------------------------------------------------------- tools
def test_open_app_launches_and_verifies(agent, launcher):
    client, _ = agent
    r = call(client, "/tool/open_app", {"app": "notepad"}).json()
    assert r["ok"] and r["verified"] and launcher.launched == [["notepad.exe"]]


def test_open_app_via_uri(agent, launcher):
    client, _ = agent
    r = call(client, "/tool/open_app", {"app": "spotify"}).json()
    assert r["verified"] and launcher.uris == ["spotify:"]


def test_tc_f04_already_running_no_second_window(agent, launcher):
    client, _ = agent
    launcher.running.add("notepad.exe")
    r = call(client, "/tool/open_app", {"app": "notepad"}).json()
    assert r["data"]["already_running"] and launcher.launched == []


def test_unverified_launch_reported_honestly(agent, launcher):
    client, _ = agent
    launcher.starts = False
    r = call(client, "/tool/open_app", {"app": "notepad"}).json()
    assert r["ok"] and not r["verified"] and r["error"]


@pytest.mark.security
@pytest.mark.parametrize("payload", [{"app": "regedit"}, {"app": "notepad; del *"}, {"app": "a" * 300},
                                     {"app": "notepad", "argv": ["cmd"]}, ["notepad"], {}])
def test_tc_s05_s06_policy_recheck_on_pc2(agent, launcher, payload):
    client, _ = agent
    r = call(client, "/tool/open_app", payload).json()
    assert not r["ok"] and r["error"].startswith("policy deny")
    assert launcher.launched == []


def test_unknown_tool_denied(agent):
    client, _ = agent
    assert call(client, "/tool/run_shell", {"cmd": "whoami"}).json()["error"] == "policy deny: unknown tool"


@pytest.mark.parametrize("url,ok", [("https://www.youtube.com/watch?v=1", True), ("https://evil.com/", False),
                                    ("http://youtube.com/", False)])
def test_tc_f23_open_url(agent, launcher, url, ok):
    client, _ = agent
    r = call(client, "/tool/open_url", {"url": url}).json()
    assert r["ok"] is ok
    if ok:
        assert launcher.launched == [["C:/chrome.exe", url]]  # URL is one argv element, no shell


@pytest.mark.security
def test_tc_r04_idempotency_key(agent, launcher):
    client, _ = agent
    r1 = call(client, "/tool/open_app", {"app": "notepad"}, key="j1:s0").json()
    launcher.running.clear()
    r2 = call(client, "/tool/open_app", {"app": "notepad"}, key="j1:s0").json()
    assert r1 == r2 and len(launcher.launched) == 1


@pytest.mark.security
def test_tc_s09_kill_switch(agent, launcher):
    client, app = agent
    assert call(client, "/killswitch", {"on": True}).json() == {"kill_switch": True}
    r = call(client, "/tool/open_app", {"app": "notepad"}).json()
    assert r["error"] == "policy deny: kill switch on" and launcher.launched == []
    st = call(client, "/status", method="GET").json()
    assert st["data"]["kill_switch"] is True  # status still works
    assert call(client, "/stop", {}).json()["ok"]
    app.state.kill.set(False)  # local reset (agent.killswitch off)
    assert call(client, "/tool/open_app", {"app": "notepad"}).json()["ok"]


def test_rate_limit_on_pc2(cfg, launcher):
    cfg.rate_limit_per_min = 3
    with TestClient(create_app(cfg, SECRET, launcher, sleep=lambda s: None)) as c:
        res = [call(c, "/tool/open_app", {"app": "notepad"}).json() for _ in range(5)]
    assert [r["ok"] for r in res] == [True, True, True, False, False]


def test_risk3_requires_matching_approval(agent, monkeypatch):
    from pydantic import BaseModel, ConfigDict

    from agent.tools import REGISTRY
    from voice_contracts import tools as tm
    from voice_contracts.models import ToolResult

    class A(BaseModel):
        model_config = ConfigDict(extra="forbid")
        text: str

    monkeypatch.setitem(tm.TOOLS, "post_social", tm.ToolSpec("post_social", 3, A, "post", 2))
    monkeypatch.setitem(REGISTRY, "post_social", lambda a, ctx: ToolResult(ok=True, verified=True))
    client, _ = agent
    payload = {"text": "hello"}
    assert "approval" in call(client, "/tool/post_social", payload).json()["error"]
    bad = {"X-Approved-Args-Hash": args_hash("post_social", {"text": "other"})}
    assert "approval" in call(client, "/tool/post_social", payload, headers=bad).json()["error"]
    good = {"X-Approved-Args-Hash": args_hash("post_social", payload)}
    assert call(client, "/tool/post_social", payload, headers=good).json()["ok"]


def test_status_lists_running_apps(agent, launcher):
    client, _ = agent
    launcher.running.add("chrome.exe")
    assert call(client, "/status", method="GET").json()["data"]["running"] == ["chrome"]


def test_audit_chain_written_and_verifiable(agent, cfg):
    client, app = agent
    call(client, "/tool/open_app", {"app": "notepad"})
    client.post("/tool/open_app", json={"app": "x"})  # auth failure is audited too
    log: AuditLog = app.state.audit
    kinds = [json.loads(line)["kind"] for line in log.path.read_text(encoding="utf-8").splitlines()]
    assert kinds == ["request", "result", "auth_fail"] and log.verify()
    lines = log.path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"open_app"', '"open_url"')
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not log.verify()


def test_signature_helper_is_deterministic():
    assert sign(SECRET, "post", "/a", "1", "n", b"") == sign(SECRET, "POST", "/a", "1", "n", b"")
