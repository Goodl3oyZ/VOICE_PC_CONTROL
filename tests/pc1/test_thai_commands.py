"""Thai commands in English mode (owner feedback 2026-10-12): the phone's Thai switch sends Thai text."""
from __future__ import annotations

import pytest

from app.core.shortcuts import match_shortcut


@pytest.mark.parametrize("text,tool,arg", [
    ("เพลงถัดไป", "media_control", ("action", "next")),
    ("เปิด YouTube", "open_url", ("url", "https://www.youtube.com/")),
    ("เล่นเพลง ลานดอกไม้", "youtube_play", ("query", "ลานดอกไม้")),
    ("เปิดเพลง Body Slam", "youtube_play", ("query", "Body Slam")),
    ("ค้นหาร้านกาแฟ ใกล้ฉัน", "web_search", ("query", "ร้านกาแฟ ใกล้ฉัน")),
    ("หยุดเพลง", "media_control", ("action", "play_pause")),
    ("เปิดเพลง ลาลาลอย", "youtube_play", ("query", "ลาลาลอย")),
    ("หาเพลง bodyslam หน่อย", "web_search", ("query", "bodyslam")),  # "find" still lists results
])
def test_thai_shortcuts(kb, rig, text, tool, arg):
    call = match_shortcut(rig.orch.normalize(text), kb)
    assert call is not None and call.tool == tool and call.arguments.get(arg[0]) == arg[1], call
