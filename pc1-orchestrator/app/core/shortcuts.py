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
_EN_READ_VERBS = {"search", "search for", "look up", "find"}  # Phase 2: read results in the agent browser
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
             "eighth": 8, "top": 1, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}
_OPEN_RESULT = re.compile(r"^(open|show|go\s+to|click)?\s*(the\s+)?((result|link|number)\s*(number\s*)?"
                          r"(?P<n>\d)|(?P<ord>first|second|third|fourth|fifth|sixth|seventh|eighth|top|1st|2nd|3rd|"
                          r"4th|5th)\s+(result|link|one))$", re.I)
_TABS = [
    (re.compile(r"^(go\s+to\s+(the\s+)?|switch\s+to\s+(the\s+)?)?next\s+tab$", re.I), "next"),
    (re.compile(r"^(go\s+to\s+(the\s+)?|switch\s+to\s+(the\s+)?)?(previous|last)\s+tab$", re.I), "previous"),
    (re.compile(r"^close\s+(this\s+|the\s+|current\s+)?tab$", re.I), "close"),
    (re.compile(r"^((list|show)\s+(the\s+|all\s+)?tabs|what\s+tabs\s+are\s+open)$", re.I), "list"),
]


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
    for rx, action in _TABS:
        if rx.match(t):
            return ToolCall(tool="browser_tabs", arguments={"action": action}, rationale="shortcut: tabs")
    m = _OPEN_RESULT.match(t)
    if m:
        n = int(m["n"]) if m["n"] else _ORDINALS[m["ord"].lower()]
        if 1 <= n <= 8:
            return ToolCall(tool="open_result", arguments={"index": n}, rationale="shortcut: open result")
    m = _SEARCH.match(t)
    if m and m["q"].strip():
        verb, q, site = m["verb"].lower(), m["q"].strip()[:200], (m["site"] or "").lower()
        if verb == "play" and site in ("", "youtube"):  # actually play it, not just list results
            return ToolCall(tool="youtube_play", arguments={"query": q}, rationale="shortcut: play")
        if " ".join(verb.split()) in _EN_READ_VERBS and not site:
            return ToolCall(tool="web_search", arguments={"query": q, "max_results": 5, "site": "web"},
                            rationale="shortcut: web search")
        music = verb in _MUSIC_VERBS
        where = "youtube" if (site == "youtube" or (music and not site)) else "web"
        # all searches run in the agent browser and reuse its search/YouTube tab (no new tab per search)
        return ToolCall(tool="web_search", arguments={"query": q, "max_results": 5, "site": where},
                        rationale="shortcut: search")
    return None


_PROJECT_CMDS = [
    (re.compile(r"^open\s+(the\s+)?project\s+(?P<p>[\w\-]+)$|^open\s+(the\s+)?(?P<p2>[\w\-]+)\s+project$", re.I),
     "open_project"),
    (re.compile(r"^(list|show)\s+(the\s+)?files\s+(in|of)\s+(the\s+)?(?P<p>[\w\-]+)(\s+project)?$", re.I),
     "list_files"),
    (re.compile(r"^(run\s+(the\s+)?tests\s+(in|for|of)\s+(the\s+)?(?P<p>[\w\-]+)(\s+project)?|"
                r"run\s+(the\s+)?(?P<p2>[\w\-]+)\s+tests|test\s+(?P<p3>[\w\-]+))$", re.I), "run_tests"),
    (re.compile(r"^(show\s+(me\s+)?(the\s+)?(diff|changes)\s+(for|in|of)\s+(the\s+)?(?P<p>[\w\-]+)(\s+project)?|"
                r"what\s+changed\s+in\s+(the\s+)?(?P<p2>[\w\-]+)(\s+project)?)$", re.I), "git_diff"),
    (re.compile(r"^(revert|undo|discard)\s+(all\s+)?(the\s+)?(ai\s+)?(changes|edits)\s+(in|for|of)\s+(the\s+)?"
                r"(?P<p>[\w\-]+)(\s+project)?$", re.I), "revert_changes"),
    (re.compile(r"^(git\s+status|status)\s+(of|for)\s+(the\s+)?(?P<p>[\w\-]+)(\s+project)?$", re.I), "git_status"),
]


def _project_cmd(text: str, kb: Knowledge) -> ToolCall | None:
    for rx, tool in _PROJECT_CMDS:
        m = rx.match(text)
        if m:
            name = next((m[g] for g in ("p", "p2", "p3") if g in rx.groupindex and m[g]), "").lower()
            if name in kb.projects:  # unknown names go to the planner (it can ask which project)
                return ToolCall(tool=tool, arguments={"project": name}, rationale="shortcut: project")
    return None


WAKE_RE = re.compile(r"^(please\s+)?(wake(\s+up)?|turn\s+on|power\s+on|switch\s+on)\s+(the\s+|my\s+)?"
                     r"(pc2?|computer|laptop|notebook)(\s+up)?\W*$", re.I)
LOOK_RE = re.compile(r"^(what('?s| is)\s+(on|in)\s+(the\s+|my\s+)?screen|describe\s+(the\s+|my\s+)?screen|"
                     r"look\s+at\s+(the\s+|my\s+)?screen|what\s+do\s+you\s+see(\s+on\s+(the\s+|my\s+)?screen)?)"
                     r"\W*$", re.I)


def match_shortcut(normalized: str, kb: Knowledge) -> ToolCall | None:
    text = " ".join(normalized.strip().strip(".!?,").split())
    text = _EN_TAIL.sub("", _EN_LEAD.sub("", text)).strip(" .!?,")
    if STOP_RE.match(text):
        return ToolCall(tool="stop_all", rationale="shortcut: stop")
    if STATUS_RE.match(text):
        return ToolCall(tool="get_status", rationale="shortcut: status")
    if WAKE_RE.match(text):
        return ToolCall(tool="wake_pc", rationale="shortcut: wake-on-lan")
    if LOOK_RE.match(text):
        return ToolCall(tool="look_at_screen", arguments={"question": "What is on the screen?"},
                        rationale="shortcut: look")
    project = _project_cmd(text, kb)
    if project is not None:
        return project
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
