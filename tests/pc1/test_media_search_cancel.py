"""Bug fixes + new Phase 1 tools: audio decoding, stuck jobs (cancel/recover/expire), search, media keys."""
from __future__ import annotations

import asyncio

import pytest

from app.adapters.fakes import ScriptedLLM
from app.core.jobs import Job, JobState
from app.core.orchestrator import Conflict
from app.core.policy import PolicyContext, decide
from app.core.shortcuts import match_shortcut
from app.ports import PlanResult
from voice_contracts.models import ToolCall
from voice_contracts.tools import search_url

S = JobState


# ---------------------------------------------------------------- shortcuts
@pytest.mark.parametrize("text,action,steps", [
    ("เพลงถัดไป", "next", None), ("ข้ามเพลงหน่อย", "next", None), ("เพลงก่อนหน้า", "previous", None),
    ("หยุดเพลง", "play_pause", None), ("เล่นเพลงต่อ", "play_pause", None), ("เปิดเพลง", "play_pause", None),
    ("ปิดเสียง", "mute", None), ("เพิ่มเสียง", "volume_up", 5), ("เพิ่มเสียง 20%", "volume_up", 10),
    ("ลดเสียง ๑๐ เปอร์เซ็นต์", "volume_down", 5), ("เบาเสียงหน่อย", "volume_down", 5),
    ("เพิ่มเสียง 100%", "volume_up", 25),
])
def test_media_shortcuts(kb, text, action, steps):
    call = match_shortcut(text, kb)
    assert call is not None and call.tool == "media_control" and call.arguments["action"] == action
    if steps:
        assert call.arguments["steps"] == steps


@pytest.mark.parametrize("text,query,site", [
    ("ค้นหาวิธีติดตั้ง docker บน windows", "วิธีติดตั้ง docker บน windows", "web"),
    ("หา lofi ใน youtube", "lofi", "youtube"),
    ("เปิดเพลง ลาลาลอย", "ลาลาลอย", "youtube"),
    ("หาเพลง bodyslam หน่อย", "bodyslam", "youtube"),
])
def test_search_shortcuts(kb, text, query, site):
    call = match_shortcut(text, kb)
    # all searches run in the agent browser (reusing its tab); search_web is disabled
    assert call is not None and call.tool == "web_search"
    assert call.arguments == {"query": query, "site": site, "max_results": 5}


def test_english_search_reads_results(kb):
    # Phase 2: English "search X" reads results in the agent browser instead of only opening Google
    assert match_shortcut("search python asyncio", kb).tool == "web_search"


def test_stop_still_means_stop_all(kb):
    assert match_shortcut("หยุด", kb).tool == "stop_all"
    assert match_shortcut("หยุดก่อน", kb).tool == "stop_all"


def test_open_app_shortcut_unchanged(kb):
    assert match_shortcut("เปิด chrome", kb).arguments == {"app": "chrome"}


# ---------------------------------------------------------------- contracts / policy
def test_search_url_is_encoded():
    assert search_url("google", "a&b=c #x") == "https://www.google.com/search?q=a%26b%3Dc+%23x"
    assert search_url("youtube", "ลาลาลอย").startswith("https://www.youtube.com/results?search_query=%E0")


@pytest.mark.security
@pytest.mark.parametrize("args", [{"query": "x", "site": "evil"}, {"query": ""}, {"query": "a" * 201},
                                  {"query": "x\n" + "y"}, {"query": "x", "url": "https://evil"}])
def test_search_bad_args_denied(kb, args):
    assert decide(ToolCall(tool="search_web", arguments=args), PolicyContext(kb)).decision == "deny"


@pytest.mark.security
@pytest.mark.parametrize("args", [{"action": "shutdown"}, {"action": "volume_up", "steps": 99},
                                  {"action": "next", "key": 13}])
def test_media_bad_args_denied(kb, args):
    assert decide(ToolCall(tool="media_control", arguments=args), PolicyContext(kb)).decision == "deny"


# ---------------------------------------------------------------- end-to-end with fakes
async def test_media_and_search_run(rig):
    from voice_contracts.models import ToolResult
    rig.pc2.handlers["media_control"] = lambda a: ToolResult(ok=True, verified=True, data={"steps": a.get("steps", 1)})
    rig.pc2.handlers["web_search"] = lambda a: ToolResult(ok=True, verified=True, untrusted=True, data={
        "results": [{"title": "Lofi Girl", "host": "youtube.com"}]})
    job = await rig.run_text("เพิ่มเสียง 20%")
    assert job.state == S.DONE and job.summary == "เพิ่มเสียงประมาณ 20% แล้ว"
    job = await rig.run_text("หา lofi ใน youtube")
    assert job.state == S.DONE and job.summary.startswith("ผลค้นหา “lofi” (YouTube): 1) Lofi Girl")


# ---------------------------------------------------------------- stuck jobs
async def _clarifying_job(rig):
    rig.llm.script = [PlanResult(kind="clarify", message="เปิดอะไรครับ?")]
    job = await rig.orch.submit_text("เปิดมัน", "phone")
    await rig.orch.wait_idle()
    return rig.orch.get_job(job.id)


async def test_cancel_clarifying_job(rig):
    job = await _clarifying_job(rig)
    assert job.state == S.CLARIFYING
    await rig.orch.cancel(job.id, "phone")
    assert rig.orch.get_job(job.id).state == S.CANCELLED
    with pytest.raises(Conflict):
        await rig.orch.cancel(job.id, "phone")


async def test_recover_closes_jobs_left_by_a_restart(rig, kb, store):
    stale = Job(id="j_stale", device="phone", source="text", text="เปิดมัน", state=S.CLARIFYING)
    store.save_job(stale.to_dict())
    from tests.conftest import Rig
    fresh = Rig(kb, store)  # simulates the service restarting with the same database
    assert await fresh.orch.recover() == 1
    assert fresh.orch.get_job("j_stale").state == S.CANCELLED
    assert store.list_unfinished_jobs() == []


async def test_cancel_stale_job_from_db(rig, store):
    store.save_job(Job(id="j_old", device="phone", source="text", state=S.CLARIFYING).to_dict())
    await rig.orch.cancel("j_old", "phone")
    assert rig.orch.get_job("j_old").state == S.CANCELLED


async def test_stop_also_clears_stale_jobs(rig, store):
    store.save_job(Job(id="j_old2", device="phone", source="text", state=S.CLARIFYING).to_dict())
    res = await rig.orch.stop("phone")
    assert rig.orch.get_job("j_old2").state == S.CANCELLED and res["pc2_stopped"]


async def test_unanswered_question_expires(rig_factory):
    rig = rig_factory(clarify_timeout_s=0.05)
    job = await _clarifying_job(rig)
    await asyncio.sleep(0.15)
    assert rig.orch.get_job(job.id).state == S.CANCELLED


def test_cancel_endpoint(api):
    client, rig, _ = api
    rig.llm.script = [PlanResult(kind="clarify", message="อะไรครับ?")]
    jid = client.post("/command", json={"text": "เปิดมัน"}).json()["id"]
    import time
    for _ in range(100):
        if client.get(f"/jobs/{jid}").json()["state"] == "clarifying":
            break
        time.sleep(0.02)
    assert client.post(f"/jobs/{jid}/cancel").json()["state"] == "cancelled"
    assert client.post(f"/jobs/{jid}/cancel").status_code == 409


# ---------------------------------------------------------------- audio decoding (bug: PyAV 19)
def test_decode_audio_webm_opus():
    av = pytest.importorskip("av", reason="PyAV not loadable here (e.g. blocked by Windows App Control)")
    np = pytest.importorskip("numpy")
    import io
    from fractions import Fraction

    from app.adapters.faster_whisper_stt import SAMPLE_RATE, decode_audio
    buf = io.BytesIO()
    with av.open(buf, mode="w", format="webm") as out:
        st = out.add_stream("libopus", rate=48000)
        st.layout = "mono"
        t = np.arange(48000) / 48000
        pcm = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
        frame.sample_rate, frame.pts, frame.time_base = 48000, 0, Fraction(1, 48000)
        for p in st.encode(frame):
            out.mux(p)
        for p in st.encode(None):
            out.mux(p)
    samples = decode_audio(buf.getvalue())
    assert samples.dtype == np.float32 and abs(len(samples) - SAMPLE_RATE) < SAMPLE_RATE * 0.1
    assert 0.1 < float(np.abs(samples).max()) <= 1.0


ScriptedLLM  # noqa: B018 (imported for parity with other test modules)


async def test_spoken_stop_does_not_wait_for_the_running_job(rig):
    """US-903: "stop" must act while another job holds PC2, not queue behind it."""
    import time
    rig.pc2.delay = 5  # a long-running tool
    long_job = await rig.orch.submit_text("open notepad", "phone")
    for _ in range(100):
        await asyncio.sleep(0.01)
        if rig.orch.get_job(long_job.id).state == S.RUNNING:
            break
    t0 = time.monotonic()
    stop_job = await rig.orch.submit_text("stop", "phone")
    for _ in range(200):
        await asyncio.sleep(0.01)
        if rig.orch.get_job(stop_job.id).terminal:
            break
    assert time.monotonic() - t0 < 1.0  # not 5 s
    assert rig.orch.get_job(stop_job.id).state == S.DONE
    assert rig.orch.get_job(long_job.id).state == S.CANCELLED and rig.pc2.stopped >= 1
    await rig.orch.wait_idle()
