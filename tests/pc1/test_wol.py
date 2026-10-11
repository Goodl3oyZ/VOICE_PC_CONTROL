"""Phase 4 Wake-on-LAN: PC1 wakes PC2 and reports whether it really came back."""
from __future__ import annotations

import pytest

from app.core import orchestrator as orch_mod
from app.core.jobs import JobState
from app.core.shortcuts import match_shortcut
from app.core.wol import magic_packet

S = JobState


def test_magic_packet():
    p = magic_packet("00-11-22-33-44-55")
    assert len(p) == 102 and p[:6] == b"\xff" * 6 and p[6:12] == bytes.fromhex("001122334455")
    assert magic_packet("00:11:22:33:44:55") == p
    with pytest.raises(ValueError):
        magic_packet("not-a-mac")


@pytest.mark.parametrize("text", ["Wake up the PC", "wake the computer", "turn on my PC", "wake pc2 up"])
def test_wake_shortcuts(kb, rig, text):
    call = match_shortcut(rig.orch.normalize(text), kb)
    assert call is not None and call.tool == "wake_pc"


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(orch_mod, "send_magic_packet", lambda mac, bc: calls.append((mac, bc)))
    return calls


async def test_wakes_and_waits_for_pc2(rig_factory, sent):
    rig = rig_factory(language="en", pc2_mac="00-11-22-33-44-55", heartbeat_enabled=True, wake_wait_s=5)
    rig.pc2.offline = True
    await rig.orch.heartbeat()
    job = await rig.run_text("open notepad")
    assert job.state == S.FAILED and "wake up the PC" in job.error  # offline hint

    async def come_back():
        import asyncio
        await asyncio.sleep(0.1)
        rig.pc2.offline = False
    import asyncio
    asyncio.get_running_loop().create_task(come_back())
    job = await rig.run_text("wake up the PC")
    assert sent == [("00-11-22-33-44-55", "255.255.255.255")]
    assert job.state == S.DONE and job.summary.startswith("PC2 is awake")


async def test_reports_honestly_when_pc2_stays_off(rig_factory, sent):
    rig = rig_factory(language="en", pc2_mac="00-11-22-33-44-55", heartbeat_enabled=True, wake_wait_s=0.2)
    rig.pc2.offline = True
    job = await rig.run_text("wake up the PC")
    assert job.state == S.FAILED and "did not come online" in job.summary and sent


async def test_not_configured(rig_factory, sent):
    rig = rig_factory(language="en")
    job = await rig.run_text("wake up the PC")
    assert job.state == S.FAILED and "VPC_PC2_MAC" in job.error and not sent
