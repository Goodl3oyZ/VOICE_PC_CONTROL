"""Real-socket E2E for the reverse connection: PC1 served by uvicorn, the agent's connector dials in over
an actual WebSocket, and commands flow PC1 -> relay -> agent (HMAC-verified) -> FakeLauncher."""
from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest
import uvicorn

from agent.config import AgentConfig
from agent.connector import hello_signature, run_connector
from agent.launcher import FakeLauncher
from agent.server import create_app as create_agent
from app.adapters.agent_hub import AgentHub, PC2RelayTools
from app.adapters.fakes import FakeSTT, ListNotifier, ScriptedLLM
from app.adapters.notify import Broadcaster
from app.api.app import create_app
from app.core.jobs import JobState
from app.core.orchestrator import Orchestrator, OrchestratorConfig

SECRET = b"relay-secret-0123456789-abcdefghijklmnop"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def relay(tmp_path, kb, store):
    hub = AgentHub(SECRET)
    orch = Orchestrator(stt=FakeSTT(), llm=ScriptedLLM(), tools=PC2RelayTools(hub, SECRET, timeout=5),
                        store=store, notify=ListNotifier(), knowledge=kb, config=OrchestratorConfig())
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(orch, store, Broadcaster(), hub=hub),
                                           host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    while not server.started:
        time.sleep(0.02)

    cfg = AgentConfig.from_dict({"apps": {"notepad": {"process": "notepad.exe", "argv": ["notepad.exe"]}},
                                 "allowed_clients": ["127.0.0.1"], "verify_timeout_s": 0.2,
                                 "data_dir": str(tmp_path / "agent")})
    launcher = FakeLauncher()
    launcher.process_for_argv0 = {"notepad.exe": "notepad.exe"}
    agent_app = create_agent(cfg, SECRET, launcher, sleep=lambda s: None)
    yield orch, hub, launcher, agent_app, f"ws://127.0.0.1:{port}/agent/ws"
    server.should_exit = True
    th.join(5)


async def wait_connected(hub, timeout=5.0):
    t0 = time.time()
    while not hub.connected:
        if time.time() - t0 > timeout:
            raise AssertionError("agent never connected")
        await asyncio.sleep(0.05)


async def test_agent_dials_out_and_runs_commands(relay):
    orch, hub, launcher, agent_app, url = relay
    task = asyncio.create_task(run_connector(agent_app, url, SECRET))
    try:
        await wait_connected(hub)
        assert await orch.heartbeat() is True
        job = await orch.submit_text("เปิดโน้ตแพด", "phone")
        await orch.wait_idle()
        job = orch.get_job(job.id)
        assert job.state == JobState.DONE and launcher.launched == [["notepad.exe"]]
        assert (await orch.stop("phone"))["pc2_stopped"] is True
    finally:
        task.cancel()


@pytest.mark.security
async def test_wrong_secret_cannot_attach(relay):
    orch, hub, launcher, agent_app, url = relay
    task = asyncio.create_task(run_connector(agent_app, url, b"wrong-secret-0123456789-abcdefghijklmno"))
    try:
        await asyncio.sleep(1.5)
        assert not hub.connected
        assert await orch.heartbeat() is False
    finally:
        task.cancel()


def test_hello_signature_matches_both_sides():
    from app.adapters.agent_hub import hello_signature as pc1_sig
    assert pc1_sig(SECRET, "c", "n") == hello_signature(SECRET, "c", "n")
