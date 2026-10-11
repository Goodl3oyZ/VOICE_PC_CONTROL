"""Phase 4 hands-free: wake-word filter and /command/wake (false triggers must not create jobs)."""
from __future__ import annotations

import asyncio

import pytest

from app.core.jobs import JobState
from app.core.wake import wake_filter

S = JobState


@pytest.mark.parametrize("text,kind,command", [
    ("Computer, open Chrome.", "command", "open Chrome."),
    ("computer open notepad", "command", "open notepad"),
    ("Hey computer, next song", "command", "next song"),
    ("OK Computer. Pause the music.", "command", "Pause the music."),
    ("Computer.", "wake_only", ""),
    ("computer", "wake_only", ""),
    ("open chrome", "ignore", ""),                      # no wake word
    ("I bought a new computer yesterday", "ignore", ""),  # wake word not at the start
    ("Thank you.", "ignore", ""),                       # Whisper's classic silence hallucination
    ("", "ignore", ""),
    ("คอมพิวเตอร์ เปิดโครม", "ignore", ""),               # not English
    ("computerized systems are great", "ignore", ""),   # not the whole word
])
def test_wake_filter(text, kind, command):
    d = wake_filter(text)
    assert (d.kind, d.command) == (kind, command)


def test_bare_stop_only_while_a_job_runs():
    assert wake_filter("Stop!", job_active=True).command == "stop"
    assert wake_filter("Stop!", job_active=False).kind == "ignore"  # "stop" in a conversation does nothing
    assert wake_filter("computer stop").command == "stop"           # with the wake word it always works


def test_armed_window_accepts_the_next_sentence():
    assert wake_filter("open notepad", armed=True) .command == "open notepad"
    assert wake_filter("ปิดเพลง", armed=True).kind == "ignore"


def _wake(client, audio: bytes, armed=False):
    return client.post(f"/command/wake?armed={'true' if armed else 'false'}",
                       files={"audio": ("s.wav", audio, "audio/wav")}).json()


def test_wake_endpoint_creates_jobs_only_for_wake_speech(api):
    client, rig, _ = api
    rig.stt.by_audio = {b"a": ("we should get pizza tonight", 0.9), b"b": ("Computer.", 0.9),
                        b"c": ("Computer, open notepad", 0.92), b"d": ("open notepad", 0.92)}
    before = len(rig.store.audit_rows())
    assert _wake(client, b"a") == {"status": "ignored"}
    assert _wake(client, b"b") == {"status": "listening"}
    assert len(rig.store.audit_rows()) == before  # ignored/wake-only speech leaves no trace
    assert _wake(client, b"d") == {"status": "ignored"}
    r = _wake(client, b"d", armed=True)
    assert r["status"] == "job" and r["job"]["text"] == "open notepad"
    r = _wake(client, b"c")
    assert r["status"] == "job" and r["job"]["text"] == "open notepad" and r["job"]["source"] == "audio"


async def test_voice_stop_during_a_running_job_is_fast(rig):
    """G4: stop by voice <= 3 s. A bare "stop" segment stops the running job without the wake word."""
    import time
    rig.pc2.delay = 5
    rig.stt.by_audio = {b"stop": ("Stop.", 0.6)}  # low confidence: Stop must still not ask
    long_job = await rig.orch.submit_text("open notepad", "phone")
    for _ in range(100):
        await asyncio.sleep(0.01)
        if rig.orch.get_job(long_job.id).state == S.RUNNING:
            break
    t0 = time.monotonic()
    r = await rig.orch.submit_wake_audio(b"stop", "audio/wav", "phone")
    assert r["status"] == "job"
    for _ in range(200):
        await asyncio.sleep(0.01)
        if rig.orch.get_job(r["job"]["id"]).terminal:
            break
    assert time.monotonic() - t0 < 1.0
    assert rig.orch.get_job(long_job.id).state == S.CANCELLED
    await rig.orch.wait_idle()
