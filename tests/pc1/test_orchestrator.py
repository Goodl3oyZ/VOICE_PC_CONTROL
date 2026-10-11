"""Use-case tests with fakes (E2E-Fake layer, §18.1): whole pipeline without GPU or PC2."""
from __future__ import annotations

import asyncio

import pytest

from app.adapters.fakes import ScriptedLLM
from app.core.jobs import JobState
from app.ports import PlanResult
from voice_contracts.models import ToolResult
from voice_contracts.tools import args_hash

S = JobState


async def test_shortcut_open_app_done(rig):
    job = await rig.run_text("เปิดโน้ตแพดให้หน่อย")
    assert job.state == S.DONE and job.outcome == "done_verified"
    assert job.planner == "shortcut" and rig.llm.calls == []  # no LLM needed (level 1)
    assert rig.pc2.calls[0]["tool"] == "open_app" and rig.pc2.calls[0]["arguments"] == {"app": "notepad"}
    assert job.summary == "เปิด Notepad แล้ว"
    states = [e["job"]["state"] for e in rig.notify.events if e["type"] == "job.update"]
    assert states == ["created", "planning", "routing", "dispatching", "running", "verifying", "done"]


async def test_tc_f04_already_running_reported(rig):
    rig.pc2.running.add("chrome")
    job = await rig.run_text("เปิดโครม")
    assert job.state == S.DONE and job.summary == "Chrome เปิดอยู่แล้ว"


async def test_tc_f05_outside_allowlist_via_llm_denied(rig):
    rig.llm.script = [ScriptedLLM.tool("open_app", app="regedit")]
    job = await rig.run_text("เปิด regedit")
    assert job.state == S.FAILED and job.outcome == "denied"
    assert rig.pc2.calls == []
    assert "ไม่อยู่ในรายการ" in job.summary
    assert any(r["kind"] == "route" and '"deny"' in r["data"] for r in rig.store.audit_rows())


async def test_llm_plan_used_for_non_shortcut(rig):
    rig.llm.script = [ScriptedLLM.tool("open_url", url="https://www.youtube.com/results?search_query=lofi")]
    job = await rig.run_text("เปิดยูทูบแล้วหาเพลง lofi")
    assert job.state == S.DONE and job.planner == "llm"
    text, ctx = rig.llm.calls[0]
    assert "youtube" in text  # normalised before planning
    assert any(t["function"]["name"] == "open_app" for t in ctx.tools)


async def test_tc_r01_invalid_json_retry_once_then_fail(rig):
    rig.llm.script = [PlanResult(kind="invalid"), PlanResult(kind="invalid")]
    job = await rig.run_text("ทำอะไรสักอย่าง")
    assert job.state == S.FAILED and len(rig.llm.calls) == 2 and rig.pc2.calls == []


async def test_invalid_then_valid_recovers(rig):
    rig.llm.script = [PlanResult(kind="invalid"), ScriptedLLM.tool("open_app", app="spotify")]
    job = await rig.run_text("อยากฟังเพลง")
    assert job.state == S.DONE


async def test_refusal_is_failed_not_done(rig):
    rig.llm.script = [PlanResult(kind="final", message="ทำไม่ได้: ไม่มีเครื่องมือโอนเงิน")]
    job = await rig.run_text("โอนเงินให้แม่ 500 บาท")
    assert job.state == S.FAILED and job.outcome == "refused" and rig.pc2.calls == []


async def test_tc_e05_llm_clarify_then_reply(rig):
    rig.llm.script = [PlanResult(kind="clarify", message="ให้เปิดแอปไหนครับ?"),
                      ScriptedLLM.tool("open_app", app="chrome")]
    job = await rig.orch.submit_text("เปิดมัน", "phone")
    await rig.orch.wait_idle()
    job = rig.orch.get_job(job.id)
    assert job.state == S.CLARIFYING and job.question == "ให้เปิดแอปไหนครับ?"
    await rig.orch.reply(job.id, "โครม", "phone")
    await rig.orch.wait_idle()
    job = rig.orch.get_job(job.id)
    assert job.state == S.DONE
    assert rig.llm.calls[1][1].history == [{"q": "ให้เปิดแอปไหนครับ?", "a": "โครม"}]


async def test_tc_f07_low_confidence_asks_before_llm(rig):
    rig.stt.text, rig.stt.confidence = "เปิดโน้ตแพด", 0.5
    job = await rig.orch.submit_audio(b"audio", "audio/webm", "phone")
    await rig.orch.wait_idle()
    job = rig.orch.get_job(job.id)
    assert job.state == S.CLARIFYING and job.clarify_kind == "stt_confirm"
    assert rig.pc2.calls == []
    await rig.orch.reply(job.id, "เปิดเครื่องคิดเลข", "phone")  # user corrects the transcript
    await rig.orch.wait_idle()
    job = rig.orch.get_job(job.id)
    assert job.state == S.DONE and rig.pc2.calls[0]["arguments"] == {"app": "calculator"}


async def test_audio_high_confidence_runs(rig):
    job = await rig.orch.submit_audio(b"audio", "audio/webm", "phone")
    await rig.orch.wait_idle()
    job = rig.orch.get_job(job.id)
    assert job.state == S.DONE and job.text == "เปิดโน้ตแพด" and "stt" in job.timings_ms


async def test_empty_transcript_fails(rig):
    rig.stt.text = "   "
    job = await rig.orch.submit_audio(b"x", "audio/webm", "phone")
    await rig.orch.wait_idle()
    assert rig.orch.get_job(job.id).state == S.FAILED


async def test_fr05_unverified_result_is_failure(rig):
    rig.pc2.fail_verify = True
    job = await rig.run_text("เปิดโน้ตแพด")
    assert job.state == S.FAILED and "ตรวจไม่พบ" in job.summary


async def test_tc_f08_stop_cancels_running_job(rig):
    rig.pc2.delay = 5
    job = await rig.orch.submit_text("เปิดโน้ตแพด", "phone")
    for _ in range(50):
        await asyncio.sleep(0.01)
        if rig.orch.get_job(job.id).state == S.RUNNING:
            break
    res = await rig.orch.stop("phone")
    await rig.orch.wait_idle()
    assert job.id in res["cancelled"] and res["pc2_stopped"] is True
    assert rig.orch.get_job(job.id).state == S.CANCELLED and rig.pc2.stopped == 1


async def test_tc_f17_pc2_offline_fails_fast(rig_factory):
    rig = rig_factory(heartbeat_enabled=True)
    rig.pc2.offline = True
    assert await rig.orch.heartbeat() is False
    job = await rig.run_text("เปิดโน้ตแพด")
    assert job.state == S.FAILED and "ออฟไลน์" in job.error
    assert {"type": "pc2.status", "online": False, "status": {}} in rig.notify.events


async def test_heartbeat_online(rig_factory):
    rig = rig_factory(heartbeat_enabled=True)
    assert await rig.orch.heartbeat() is True and rig.orch.pc2_online


async def test_tc_r02_pc2_unreachable_and_circuit_breaker(rig):
    rig.pc2.offline = True
    for _ in range(3):
        job = await rig.run_text("เปิดโน้ตแพด")
        assert job.state == S.FAILED and "ติดต่อ PC2 ไม่ได้" in job.error
    rig.pc2.offline = False
    job = await rig.run_text("เปิดโน้ตแพด")
    assert "circuit breaker" in job.error and rig.pc2.calls == []


async def test_tc_r05_audit_failure_fails_closed(rig, monkeypatch):
    original = rig.store.append_audit

    def broken(kind, job_id, data):
        if kind == "state" and data.get("to") == "dispatching":
            raise OSError("disk full")
        return original(kind, job_id, data)

    monkeypatch.setattr(rig.store, "append_audit", broken)
    job = await rig.run_text("เปิดโน้ตแพด")
    assert job.state == S.FAILED and "fail closed" in job.error
    assert rig.pc2.calls == []  # nothing reached PC2


async def test_pc2_kill_switch_reported_blocks_actions(rig):
    rig.pc2.kill_switch = True
    await rig.orch.heartbeat()
    job = await rig.run_text("เปิดโน้ตแพด")
    assert job.state == S.FAILED and job.outcome == "denied"


# ---------------------------------------------------------------- confirmation (risk >= 3)
async def _risky_job(rig):
    rig.llm.script = [ScriptedLLM.tool("send_message", to="mom", text="ถึงบ้านแล้ว")]
    rig.pc2.handlers["send_message"] = lambda a: ToolResult(ok=True, verified=True, data={"sent": True})
    job = await rig.orch.submit_text("ส่งข้อความหาแม่ว่าถึงบ้านแล้ว", "phone")
    await rig.orch.wait_idle()
    return rig.orch.get_job(job.id)


async def test_tc_f11_confirm_approve_runs_exact_args(rig, risky_tool):
    job = await _risky_job(rig)
    assert job.state == S.AWAITING_CONFIRM and rig.pc2.calls == []
    expected = args_hash("send_message", {"to": "mom", "text": "ถึงบ้านแล้ว"})
    assert job.pending["args_hash"] == expected
    await rig.orch.confirm(job.id, True, expected, "phone")
    await rig.orch.wait_idle()
    assert rig.orch.get_job(job.id).state == S.DONE
    assert rig.pc2.calls[0]["approved_hash"] == expected


async def test_tc_f11_reject_cancels(rig, risky_tool):
    job = await _risky_job(rig)
    await rig.orch.confirm(job.id, False, job.pending["args_hash"], "phone")
    assert rig.orch.get_job(job.id).state == S.CANCELLED and rig.pc2.calls == []


async def test_tc_f11_timeout_cancels(rig_factory, risky_tool):
    rig = rig_factory(confirm_timeout_s=0.05)
    job = await _risky_job(rig)
    await asyncio.sleep(0.15)
    assert rig.orch.get_job(job.id).state == S.CANCELLED and rig.pc2.calls == []


@pytest.mark.security
async def test_tc_s16_tampered_hash_denied(rig, risky_tool):
    job = await _risky_job(rig)
    await rig.orch.confirm(job.id, True, args_hash("send_message", {"to": "boss", "text": "x"}), "phone")
    assert rig.orch.get_job(job.id).state == S.FAILED and rig.pc2.calls == []


async def test_confirm_wrong_state_conflict(rig):
    from app.core.orchestrator import Conflict
    job = await rig.run_text("เปิดโน้ตแพด")
    with pytest.raises(Conflict):
        await rig.orch.confirm(job.id, True, "sha256:x", "phone")


# ---------------------------------------------------------------- loop guard (§14.6)
async def test_loop_guard_repeated_call(rig_factory):
    rig = rig_factory(multi_step=True)
    rig.llm.script = lambda text, ctx: ScriptedLLM.tool("open_app", app="chrome")
    job = await rig.run_text("ทำซ้ำไปเรื่อยๆ")
    assert job.state == S.FAILED and "loop guard" in job.error and len(rig.pc2.calls) == 1


async def test_loop_guard_max_steps(rig_factory):
    rig = rig_factory(multi_step=True, max_steps=3)
    apps = iter(["chrome", "notepad", "spotify", "calculator"])
    rig.llm.script = lambda text, ctx: ScriptedLLM.tool("open_app", app=next(apps))
    job = await rig.run_text("เปิดทุกอย่าง")
    assert job.state == S.FAILED and len(rig.pc2.calls) == 3


async def test_multi_step_final_after_tool_is_done(rig_factory):
    rig = rig_factory(multi_step=True)
    rig.llm.script = [ScriptedLLM.tool("open_app", app="chrome"), PlanResult(kind="final", message="เสร็จ")]
    job = await rig.run_text("เปิดโครมแล้วบอกด้วย")
    assert job.state == S.DONE
    assert rig.llm.calls[1][1].observations[0]["tool"] == "open_app"


async def test_job_timeout(rig_factory):
    rig = rig_factory(job_timeout_s=0.05)
    rig.llm = rig.orch.llm = ScriptedLLM([ScriptedLLM.tool("open_app", app="chrome")], delay=1)
    job = await rig.run_text("อะไรก็ได้")
    assert job.state == S.FAILED and "timeout" in job.error


async def test_timings_and_events_recorded(rig):
    job = await rig.run_text("เปิดโน้ตแพด")
    stages = {e["stage"] for e in rig.store.events(job.id)}
    assert {"route", "tool", "job"} <= stages and "total" in job.timings_ms
    assert rig.store.verify_audit()
