"""Store + HTTP/WebSocket API tests (contract/integration layer)."""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.core.orchestrator import Orchestrator, OrchestratorConfig


# ---------------------------------------------------------------- store
@pytest.mark.security
def test_tc_s10_audit_tamper_detected(store):
    for i in range(5):
        store.append_audit("state", f"j{i}", {"to": "done"})
    assert store.verify_audit()
    store._db.execute("UPDATE audit SET data=? WHERE seq=3", (json.dumps({"to": "failed"}),))
    assert not store.verify_audit()


def test_tc_f28_device_revoke(store):
    t1, t2 = store.create_device("phone1"), store.create_device("phone2")
    assert store.check_token(t1) == "phone1"
    assert store.revoke_device("phone1")
    assert store.check_token(t1) is None and store.check_token(t2) == "phone2"
    assert store.check_token("") is None and store.check_token("x" * 1000) is None


def test_tc_f18_history_newest_first_limit_50(store):
    for i in range(60):
        store.save_job({"id": f"j{i:02d}", "created_at": 1000 + i, "updated_at": 1000 + i,
                        "state": "done", "text": f"cmd {i}"})
    jobs = store.list_jobs(50)
    assert len(jobs) == 50 and jobs[0]["id"] == "j59" and jobs[-1]["id"] == "j10"


# ---------------------------------------------------------------- API


def _wait_state(client, job_id, states, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["state"] in states:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job stuck in {job['state']}")


@pytest.mark.security
@pytest.mark.parametrize("header", [None, "Bearer wrong", "Basic abc", "Bearer "])
def test_tc_f22_bad_token_401_and_no_job(api, header):
    client, rig, _ = api
    headers = {} if header is None else {"Authorization": header}
    with TestClient(client.app) as anon:
        r = anon.post("/command", json={"text": "เปิดโน้ตแพด"}, headers=headers)
    assert r.status_code == 401
    assert rig.store.list_jobs() == []


def test_command_flow_and_history(api):
    client, rig, _ = api
    r = client.post("/command", json={"text": "เปิดโน้ตแพด"})
    assert r.status_code == 202
    job = _wait_state(client, r.json()["id"], {"done", "failed"})
    assert job["state"] == "done" and job["summary"] == "เปิด Notepad แล้ว"
    assert client.get("/jobs").json()[0]["id"] == job["id"]
    assert "history" not in job


def test_audio_upload(api):
    client, rig, _ = api
    r = client.post("/command/audio", files={"audio": ("c.webm", b"\x1a\x45\xdf\xa3", "audio/webm")})
    assert r.status_code == 202
    assert _wait_state(client, r.json()["id"], {"done", "failed"})["state"] == "done"


def test_audio_rejects_non_audio(api):
    client, *_ = api
    r = client.post("/command/audio", files={"audio": ("x.html", b"<script>", "text/html")})
    assert r.status_code == 415


def test_command_validation(api):
    client, *_ = api
    assert client.post("/command", json={"text": ""}).status_code == 422
    assert client.post("/command", json={"text": "x" * 1001}).status_code == 422


def test_unknown_job_404_and_reply_conflict(api):
    client, *_ = api
    assert client.get("/jobs/nope").status_code == 404
    r = client.post("/command", json={"text": "เปิดโน้ตแพด"})
    _wait_state(client, r.json()["id"], {"done"})
    assert client.post(f"/jobs/{r.json()['id']}/reply", json={"text": "ใช่"}).status_code == 409


def test_stop_endpoint(api):
    client, rig, _ = api
    r = client.post("/stop")
    assert r.status_code == 200 and r.json()["pc2_stopped"] is True


def test_status_endpoint(api):
    client, *_ = api
    assert client.get("/status").json()["pc2_online"] is False


def test_security_headers(api):
    client, *_ = api
    h = client.get("/health").headers
    assert h["x-content-type-options"] == "nosniff" and "frame-ancestors 'none'" in h["content-security-policy"]


def test_websocket_events(api):
    client, rig, token = api
    with client.websocket_connect(f"/events?token={token}") as ws:
        assert ws.receive_json()["type"] == "pc2.status"
        assert client.post("/command", json={"text": "เปิดโน้ตแพด"}).status_code == 202
        states = []
        while "done" not in states:
            ev = ws.receive_json()
            if ev["type"] == "job.update":
                states.append(ev["job"]["state"])
    assert states[0] == "created"


def test_websocket_rejects_bad_token(api):
    client, *_ = api
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/events?token=bad") as ws:
        ws.receive_json()


def test_confirm_endpoint_flow(api, risky_tool):
    from app.adapters.fakes import ScriptedLLM
    from voice_contracts.models import ToolResult
    client, rig, _ = api
    rig.llm.script = [ScriptedLLM.tool("send_message", to="mom", text="hi")]
    rig.pc2.handlers["send_message"] = lambda a: ToolResult(ok=True, verified=True)
    r = client.post("/command", json={"text": "ส่งข้อความหาแม่"})
    job = _wait_state(client, r.json()["id"], {"awaiting_confirm"})
    r = client.post(f"/confirm/{job['id']}", json={"approve": True, "args_hash": job["pending"]["args_hash"]})
    assert r.status_code == 200
    assert _wait_state(client, job["id"], {"done", "failed"})["state"] == "done"


def test_main_build_with_fakes(tmp_path, monkeypatch):
    monkeypatch.setenv("VPC_DB", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("VPC_STATIC_DIR", str(tmp_path / "nope"))
    from app.main import build
    with TestClient(build()) as c:
        assert c.get("/health").json() == {"ok": True}


def test_orchestrator_config_defaults():
    cfg = OrchestratorConfig()
    assert cfg.confirm_timeout_s == 120 and cfg.max_steps == 8 and not cfg.multi_step
    assert Orchestrator  # imported for completeness
