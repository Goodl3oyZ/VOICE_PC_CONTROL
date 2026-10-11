"""Phase 4 vision: 'what's on the screen?' — the screenshot is described and never stored."""
from __future__ import annotations

import json

import pytest

from app.core.jobs import JobState
from app.core.shortcuts import match_shortcut
from voice_contracts.models import ToolResult

S = JobState


@pytest.mark.parametrize("text", ["What's on the screen?", "what is on my screen", "Describe the screen",
                                  "look at the screen", "What do you see?"])
def test_look_shortcuts(kb, rig, text):
    call = match_shortcut(rig.orch.normalize(text), kb)
    assert call is not None and call.tool == "look_at_screen"


async def test_screenshot_is_described_and_dropped(rig_factory):
    rig = rig_factory(language="en")
    rig.pc2.handlers["look_at_screen"] = lambda a: ToolResult(
        ok=True, verified=True, untrusted=True, data={"image_jpeg_b64": "SECRET_PIXELS", "screen": [1920, 1080]})
    job = await rig.run_text("What's on the screen?")
    assert job.state == S.DONE and job.summary == "A code editor is open." and rig.llm.images_seen == 1
    assert job.tainted  # screen text is untrusted
    stored = json.dumps(rig.store.get_job(job.id)) + json.dumps(rig.store.audit_rows())
    assert "SECRET_PIXELS" not in stored and "SECRET_PIXELS" not in json.dumps(job.public())


async def test_vision_failure_is_reported(rig_factory):
    rig = rig_factory(language="en")
    rig.pc2.handlers["look_at_screen"] = lambda a: ToolResult(ok=True, verified=True, data={"image_jpeg_b64": "x"})
    rig.llm.vision_answer = ""
    job = await rig.run_text("describe the screen")
    assert job.state == S.FAILED
