"""Level-1 control: canned commands matched by rules, no LLM needed (doc §5, §14.5).

Only matches when the whole sentence is "<verb> <one known target> <polite particles>".
Anything with extra content is left to the LLM planner.
"""
from __future__ import annotations

import re

from voice_contracts.models import ToolCall

from .knowledge import Knowledge

OPEN_WORDS = ("เปิด", "open")
STOP_RE = re.compile(r"^(หยุด|stop|ยกเลิก)(ก่อน|เลย|ทั้งหมด|งาน|ทุกอย่าง|\s)*$", re.IGNORECASE)
STATUS_RE = re.compile(r"^(ดู)?สถานะ(เครื่อง|pc2|\s)*$", re.IGNORECASE)
# Filler that doesn't change meaning: polite particles, "program/app/web", "please".
FILLER = [
    "ให้หน่อย", "หน่อยครับ", "หน่อยค่ะ", "หน่อย", "ให้ที", "ที", "ครับ", "ค่ะ", "คะ", "นะ", "จ้า",
    "เลย", "โปรแกรม", "แอปพลิเคชัน", "แอป", "แอพ", "เว็บไซต์", "เว็บ", "ให้", "please", "app",
    "ขึ้นมา", "ด้วย",
]
_FILLER_RE = re.compile("|".join(re.escape(f) for f in sorted(FILLER, key=len, reverse=True)),
                        re.IGNORECASE)


def match_shortcut(normalized: str, kb: Knowledge) -> ToolCall | None:
    text = normalized.strip()
    if STOP_RE.match(text):
        return ToolCall(tool="stop_all", rationale="shortcut: stop")
    if STATUS_RE.match(text):
        return ToolCall(tool="get_status", rationale="shortcut: status")

    lowered = text.lower()
    verb = next((v for v in OPEN_WORDS if lowered.startswith(v)), None)
    if verb is None:
        return None
    rest = text[len(verb):]
    targets = [t for t in rest.split() if t.lower() in kb.apps or t.lower() in kb.sites]
    if len(targets) != 1:
        return None
    target = targets[0].lower()
    leftover = _FILLER_RE.sub(" ", rest.replace(targets[0], " ", 1)).strip()
    if leftover:
        return None  # more than "open X" -> needs the planner
    if target in kb.apps:
        return ToolCall(tool="open_app", arguments={"app": target}, rationale="shortcut: open app")
    return ToolCall(tool="open_url", arguments={"url": kb.sites[target]}, rationale="shortcut: open site")
