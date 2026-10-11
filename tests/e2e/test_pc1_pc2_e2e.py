"""E2E across the real PC1 -> PC2 boundary: orchestrator + PC2HttpTools (HMAC) + agent app.

Only the OS launcher, STT and LLM are faked; signing, policy on both sides, idempotency and
verification all run for real (§18.1 "E2E + Fake").
"""
from __future__ import annotations

import httpx
import pytest

from agent.config import AgentConfig
from agent.launcher import FakeLauncher
from agent.server import create_app as create_agent
from app.adapters.fakes import FakeSTT, ListNotifier, ScriptedLLM
from app.adapters.pc2_http import PC2HttpTools
from app.core.jobs import JobState
from app.core.orchestrator import Orchestrator, OrchestratorConfig

SECRET = b"e2e-secret-0123456789-abcdefghijklmnop"


@pytest.fixture
def system(tmp_path, kb, store):
    cfg = AgentConfig.from_dict({
        "apps": {"chrome": {"process": "chrome.exe", "argv": ["chrome.exe"]},
                 "notepad": {"process": "notepad.exe", "argv": ["notepad.exe"]}},
        "browser_argv": ["chrome.exe"], "allowed_hosts": ["youtube.com", "google.com"],
        "allowed_clients": [], "verify_timeout_s": 0.2, "data_dir": str(tmp_path / "agent"),
    })
    launcher = FakeLauncher()
    launcher.process_for_argv0 = {"chrome.exe": "chrome.exe", "notepad.exe": "notepad.exe"}
    agent_app = create_agent(cfg, SECRET, launcher, sleep=lambda s: None)

    def tools(secret: bytes = SECRET) -> PC2HttpTools:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_app), base_url="http://pc2")
        return PC2HttpTools("http://pc2", secret, client=client)

    llm = ScriptedLLM()
    orch = Orchestrator(stt=FakeSTT("เปิดโครมหน่อย"), llm=llm, tools=tools(), store=store,
                        notify=ListNotifier(), knowledge=kb, config=OrchestratorConfig(heartbeat_enabled=True))
    return orch, launcher, llm, agent_app, tools


async def run(orch, text):
    job = await orch.submit_text(text, "phone")
    await orch.wait_idle()
    return orch.get_job(job.id)


async def test_voice_command_opens_app_end_to_end(system):
    orch, launcher, *_ = system
    assert await orch.heartbeat() is True
    job = await orch.submit_audio(b"voice", "audio/webm", "phone")
    await orch.wait_idle()
    job = orch.get_job(job.id)
    assert job.state == JobState.DONE and job.summary == "เปิด Chrome แล้ว"
    assert launcher.launched == [["chrome.exe"]]


async def test_pc1_allowlist_bigger_than_pc2_still_blocked(system):
    """spotify is allowed in PC1 knowledge but not configured on PC2 -> PC2 denies (defense in depth)."""
    orch, launcher, *_ = system
    await orch.heartbeat()
    job = await run(orch, "เปิดสปอติฟาย")
    assert job.state == JobState.FAILED and "policy deny" in job.summary
    assert launcher.launched == []


async def test_open_site(system):
    orch, launcher, *_ = system
    await orch.heartbeat()
    job = await run(orch, "เปิดยูทูบ")
    assert job.state == JobState.DONE and launcher.launched == [["chrome.exe", "https://www.youtube.com/"]]


async def test_status_and_stop_reach_agent(system):
    orch, launcher, *_ = system
    launcher.running.add("notepad.exe")
    await orch.heartbeat()
    assert orch.pc2_status["running"] == ["notepad"]
    res = await orch.stop("phone")
    assert res["pc2_stopped"] is True


async def test_wrong_secret_rejected_by_agent(system):
    orch, launcher, llm, agent_app, tools = system
    orch.tools = tools(b"wrong-secret-0123456789-abcdefghijklmno")
    assert await orch.heartbeat() is False  # status call is rejected too
    orch.cfg.heartbeat_enabled = False  # skip the offline short-circuit to hit the agent directly
    job = await run(orch, "เปิดโน้ตแพด")
    assert job.state == JobState.FAILED and "401" in job.summary and launcher.launched == []
