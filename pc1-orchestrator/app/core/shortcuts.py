"""Level-1 control: canned commands matched by rules, no LLM needed (doc §5, §14.5).

Only matches when the whole sentence is "<verb> <one known target> <polite particles>".
Anything with extra content is left to the LLM planner.
"""
from __future__ import annotations

import re

from voice_contracts.models import ToolCall

from .knowledge import Knowledge

OPEN_WORDS = ("เปิด", "open")
STOP_RE = re.compile(r"^(หยุด|stop|ยกเลิก|cancel)(ก่อน|เลย|ทั้งหมด|งาน|ทุกอย่าง|\s|it|everything|all|now|that)*$",
                     re.IGNORECASE)
STATUS_RE = re.compile(r"^((ดู)?สถานะ(เครื่อง|pc2|\s)*|(show\s+)?(pc2?\s+|computer\s+)?status|"
                       r"what('s| is)\s+(open|running)(\s+on\s+(the\s+)?(pc2?|computer))?)$", re.IGNORECASE)
# English: leading/trailing politeness and punctuation that Whisper adds ("Open Chrome, please.")
_EN_LEAD = re.compile(r"^(please|hey|ok(ay)?|can you|could you|would you|i want to|i'd like to)\s+", re.I)
_EN_TAIL = re.compile(r"\s+(please|for me|now|thanks|thank you)$", re.I)
_EN_FILLER = re.compile(r"\b(the|app|application|program|browser|website|site|up)\b", re.I)
# Filler that doesn't change meaning: polite particles, "program/app/web", "please".
FILLER = [
    "ให้หน่อย", "หน่อยครับ", "หน่อยค่ะ", "หน่อย", "ให้ที", "ที", "ครับ", "ค่ะ", "คะ", "นะ", "จ้า",
    "เลย", "โปรแกรม", "แอปพลิเคชัน", "แอป", "แอพ", "เว็บไซต์", "เว็บ", "ให้", "please", "app",
    "ขึ้นมา", "ด้วย",
]
_FILLER_RE = re.compile("|".join(re.escape(f) for f in sorted(FILLER, key=len, reverse=True)),
                        re.IGNORECASE)
_POLITE_TAIL = re.compile(r"(\s*(ให้หน่อย|หน่อยครับ|หน่อยค่ะ|หน่อย|ให้ที|ครับ|ค่ะ|คะ|นะ|จ้า|ที))+$")
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

# Media keys (work for Spotify, YouTube in Chrome, ...). Matched on the whole sentence minus polite tail.
_MEDIA = [
    (re.compile(r"^(เพลงถัดไป|ข้ามเพลง|เพลงต่อไป|เปลี่ยนเพลง|ถัดไป|(play\s+)?next(\s+(song|track|video))?|"
                r"skip(\s+(this\s+)?(song|track|video))?)$", re.I), "next"),
    (re.compile(r"^(เพลงก่อนหน้า|ย้อนเพลง|เพลงที่แล้ว|ย้อนกลับ|(play\s+)?previous(\s+(song|track|video))?|"
                r"go\s+back(\s+a\s+(song|track))?|last\s+(song|track))$", re.I), "previous"),
    (re.compile(r"^(หยุดเพลง|พักเพลง|หยุดชั่วคราว|เล่นเพลงต่อ|เล่นต่อ|เล่นเพลง|เปิดเพลง|pause|play|resume|"
                r"(pause|resume|play)\s+(the\s+)?(music|song|video|track)|continue(\s+playing)?)$", re.I),
     "play_pause"),
    (re.compile(r"^(ปิดเสียง|เปิดเสียง|(un)?mute(\s+(the\s+)?(sound|audio|volume|music))?)$", re.I), "mute"),
]
_VOLUME = re.compile(r"^(?P<verb>เพิ่มเสียง|เสียงดังขึ้น|เร่งเสียง|ดังขึ้น|ลดเสียง|เสียงเบาลง|เบาเสียง|เบาลง|"
                     r"volume\s+up|volume\s+down|turn\s+(it\s+|the\s+volume\s+)?up|turn\s+(it\s+|the\s+volume\s+)?down|"
                     r"louder|quieter|softer|(raise|increase)\s+(the\s+)?volume|(lower|decrease|reduce)\s+(the\s+)?volume)"
                     r"(\s*(อีก|by)?\s*(?P<num>\d{1,3})\s*(%|เปอร์เซ็นต์|percent)?)?$", re.I)
_VOLUME_UP = re.compile(r"เพิ่ม|ดังขึ้น|เร่ง|up|louder|raise|increase", re.I)
# "ค้นหา X", "หา X ใน youtube", "เปิดเพลง X (ใน youtube)" -> search results page
_SEARCH = re.compile(r"^(?P<verb>หาเพลง|ค้นหา|หา|search\s+for|search|look\s+up|google|find|เสิร์ช|เปิดเพลง|"
                     r"เล่นเพลง|play)\s*(?P<q>.+?)"
                     r"(\s*(ใน|บน|ที่|จาก|on|in)\s*(?P<site>youtube|google))?$", re.I)
_MUSIC_VERBS = {"หาเพลง", "เปิดเพลง", "เล่นเพลง", "play"}


def _media_or_search(text: str) -> ToolCall | None:
    t = _POLITE_TAIL.sub("", text.translate(_THAI_DIGITS)).strip()
    t = _EN_TAIL.sub("", _EN_LEAD.sub("", t)).strip()
    for rx, action in _MEDIA:
        if rx.match(t):
            return ToolCall(tool="media_control", arguments={"action": action}, rationale="shortcut: media")
    m = _VOLUME.match(t)
    if m:
        up = bool(_VOLUME_UP.search(m["verb"]))
        steps = max(1, min(25, round(int(m["num"]) / 2))) if m["num"] else 5  # 1 step = 2 %
        return ToolCall(tool="media_control", arguments={"action": "volume_up" if up else "volume_down",
                                                         "steps": steps}, rationale="shortcut: volume")
    m = _SEARCH.match(t)
    if m and m["q"].strip():
        music = m["verb"].lower() in _MUSIC_VERBS
        site = (m["site"] or ("youtube" if music else "google")).lower()
        return ToolCall(tool="search_web", arguments={"query": m["q"].strip()[:200], "site": site},
                        rationale="shortcut: search")
    return None


def match_shortcut(normalized: str, kb: Knowledge) -> ToolCall | None:
    text = " ".join(normalized.strip().strip(".!?,").split())
    text = _EN_TAIL.sub("", _EN_LEAD.sub("", text)).strip(" .!?,")
    if STOP_RE.match(text):
        return ToolCall(tool="stop_all", rationale="shortcut: stop")
    if STATUS_RE.match(text):
        return ToolCall(tool="get_status", rationale="shortcut: status")
    media = _media_or_search(text)
    if media is not None:
        return media

    lowered = text.lower()
    verb = next((v for v in OPEN_WORDS if lowered.startswith(v)), None)
    if verb is None:
        return None
    rest = text[len(verb):]
    targets = [t for t in rest.split() if t.lower() in kb.apps or t.lower() in kb.sites]
    if len(targets) != 1:
        return None
    target = targets[0].lower()
    leftover = _EN_FILLER.sub(" ", _FILLER_RE.sub(" ", rest.replace(targets[0], " ", 1))).strip(" .,!?")
    if leftover:
        return None  # more than "open X" -> needs the planner
    if target in kb.apps:
        return ToolCall(tool="open_app", arguments={"app": target}, rationale="shortcut: open app")
    return ToolCall(tool="open_url", arguments={"url": kb.sites[target]}, rationale="shortcut: open site")
