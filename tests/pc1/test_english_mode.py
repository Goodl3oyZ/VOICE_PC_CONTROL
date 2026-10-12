"""English-only mode (VPC_LANGUAGE=en): English shortcuts, English replies, other languages rejected."""
from __future__ import annotations

import pytest

from app.adapters.ollama_llm import parse_message
from app.core.i18n import is_english, is_english_or_thai
from app.core.jobs import JobState
from app.core.shortcuts import match_shortcut
from app.ports import PlanResult

S = JobState


@pytest.mark.parametrize("text,ok", [
    ("Open Chrome.", True), ("volume up 20%", True), ("play lofi on youtube", True),
    ("เปิดโครม", False), ("เปิด Chrome หน่อย", False), ("こんにちは", False), ("Открой хром", False),
    ("123 !!", False), ("Open notepad, por favor", True),
])
def test_is_english(text, ok):
    assert is_english(text) is ok


@pytest.mark.parametrize("text,tool,args", [
    ("Open Chrome.", "open_app", {"app": "chrome"}),
    ("Please open notepad", "open_app", {"app": "notepad"}),
    ("can you open the calculator for me", "open_app", {"app": "calculator"}),
    ("Open YouTube", "open_url", {"url": "https://www.youtube.com/"}),
    ("Stop.", "stop_all", {}),
    ("stop everything", "stop_all", {}),
    ("Status", "get_status", {}),
    ("what's running on the pc", "get_status", {}),
    ("Next song", "media_control", {"action": "next"}),
    ("skip this track", "media_control", {"action": "next"}),
    ("previous track", "media_control", {"action": "previous"}),
    ("Pause the music.", "media_control", {"action": "play_pause"}),
    ("resume", "media_control", {"action": "play_pause"}),
    ("mute", "media_control", {"action": "mute"}),
    ("Volume up 20%", "media_control", {"action": "volume_up", "steps": 10}),
    ("turn the volume down", "media_control", {"action": "volume_down", "steps": 5}),
    ("louder", "media_control", {"action": "volume_up", "steps": 5}),
    ("lower the volume by 10 percent", "media_control", {"action": "volume_down", "steps": 5}),
    ("Search for weather in Bangkok", "web_search", {"query": "weather in Bangkok", "max_results": 5, "site": "web"}),
    ("Play lofi hip hop on YouTube.", "youtube_play", {"query": "lofi hip hop"}),
    ("play bodyslam", "youtube_play", {"query": "bodyslam"}),
    ("look up python asyncio", "web_search", {"query": "python asyncio", "max_results": 5, "site": "web"}),
    ("search docker on google", "web_search", {"query": "docker", "max_results": 5, "site": "web"}),
    ("search lofi on youtube", "web_search", {"query": "lofi", "max_results": 5, "site": "youtube"}),
    ("open result 2", "open_result", {"index": 2}),
    ("Open the first result.", "open_result", {"index": 1}),
    ("third link", "open_result", {"index": 3}),
    ("next tab", "browser_tabs", {"action": "next"}),
    ("go to the previous tab", "browser_tabs", {"action": "previous"}),
    ("close this tab", "browser_tabs", {"action": "close"}),
    ("what tabs are open", "browser_tabs", {"action": "list"}),
])
def test_english_shortcuts(kb, rig, text, tool, args):
    call = match_shortcut(rig.orch.normalize(text), kb)
    assert call is not None and call.tool == tool and call.arguments == args, call


@pytest.mark.parametrize("text", ["open chrome and search docker", "open it", "close chrome"])
def test_english_needs_planner(kb, rig, text):
    assert match_shortcut(rig.orch.normalize(text), kb) is None


def test_parse_english_prefixes():
    assert parse_message({"content": "ASK: Which app?"}).kind == "clarify"
    r = parse_message({"content": "NO: I can't delete files."})
    assert r.kind == "final" and r.message == "I can't delete files."


async def test_english_text_runs_with_english_summary(rig_factory):
    rig = rig_factory(language="en")
    job = await rig.run_text("Open Notepad please.")
    assert job.state == S.DONE and job.summary == "Opened Notepad"
    job = await rig.run_text("open the calculator")
    assert job.summary == "Opened Calculator"  # English display name, not the Thai one


async def test_thai_text_accepted_in_english_mode(rig_factory):
    """Owner feedback 2026-10-12: Thai song names and Thai commands must work; the phone shows the transcript
    before sending, so Thai is no longer refused."""
    rig = rig_factory(language="en")
    job = await rig.run_text("เปิดโครม")
    assert job.outcome != "rejected_language"


@pytest.mark.parametrize("text,ok", [
    ("play ลานดอกไม้", True), ("เปิด Chrome หน่อย", True), ("Open Chrome", True),
    ("こんにちは", False), ("Открой хром", False), ("123", False),
])
def test_english_or_thai(text, ok):
    assert is_english_or_thai(text) is ok


async def test_other_languages_still_rejected(rig_factory):
    rig = rig_factory(language="en")
    job = await rig.run_text("Открой хром")
    assert job.state == S.FAILED and job.outcome == "rejected_language"
    assert job.error.startswith("Only English or Thai") and rig.pc2.calls == [] and rig.llm.calls == []


async def test_other_language_speech_rejected(rig_factory):
    rig = rig_factory(language="en")
    rig.stt.text, rig.stt.confidence = "こんにちは", 0.9
    job = await rig.orch.submit_audio(b"x", "audio/webm", "phone")
    await rig.orch.wait_idle()
    job = rig.orch.get_job(job.id)
    assert job.outcome == "rejected_language" and rig.pc2.calls == []


async def test_stt_review_uses_the_phone_language(rig_factory):
    rig = rig_factory(language="en")
    rig.stt.text, rig.stt.confidence = "เล่นเพลง ลานดอกไม้", 0.8
    assert await rig.orch.transcribe(b"x", "audio/webm", "th") == {"text": "เล่นเพลง ลานดอกไม้", "confidence": 0.8}
    assert rig.stt.languages == ["th"] and rig.orch.list_jobs(10) == []  # review only: no job


async def test_english_messages_for_errors(rig_factory):
    rig = rig_factory(language="en")
    rig.llm.script = [PlanResult(kind="clarify", message="Which app?")]
    job = await rig.orch.submit_text("open it", "phone")
    await rig.orch.wait_idle()
    with pytest.raises(ValueError, match="Only English or Thai"):
        await rig.orch.reply(job.id, "Хром", "phone")
    await rig.orch.reply(job.id, "chrome", "phone")  # English answer accepted
    rig.pc2.offline = True
    job = await rig.run_text("open notepad")
    assert job.error.startswith("Cannot reach PC2")


async def test_english_deny_message(rig_factory):
    from app.adapters.fakes import ScriptedLLM
    rig = rig_factory(language="en")
    rig.llm.script = [ScriptedLLM.tool("open_app", app="regedit")]
    job = await rig.run_text("I need to tweak some registry values")  # "open regedit" is refused by rule first
    assert job.summary == "This app is not on the allowed list"


def test_low_confidence_question_in_english(rig_factory):
    from app.core.i18n import Messages
    assert Messages("en")("stt_confirm", text="open chrome").startswith('I heard "open chrome"')


async def test_low_confidence_stop_runs_immediately(rig_factory):
    rig = rig_factory(language="en")
    rig.stt.text, rig.stt.confidence = "Stop everything.", 0.3
    job = await rig.orch.submit_audio(b"x", "audio/webm", "phone")
    await rig.orch.wait_idle()
    job = rig.orch.get_job(job.id)
    assert job.state == S.DONE and rig.pc2.stopped == 1  # no "is that right?" question for Stop


async def test_low_confidence_other_command_still_asks(rig_factory):
    rig = rig_factory(language="en")
    rig.stt.text, rig.stt.confidence = "Open notepad", 0.3
    job = await rig.orch.submit_audio(b"x", "audio/webm", "phone")
    await rig.orch.wait_idle()
    job = rig.orch.get_job(job.id)
    assert job.state == S.CLARIFYING and job.question.startswith('I heard "Open notepad"')
