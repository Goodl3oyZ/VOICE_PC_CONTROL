"""What the user can say — single source for the PWA guide and the "help" voice command.

App and site examples are generated from System Knowledge, so the guide always matches the allowlist.
tests/pc1/test_capabilities.py runs every example through the real shortcut parser and policy.
"""
from __future__ import annotations

import re
from typing import Any

from .knowledge import Knowledge

HELP_RE = re.compile(r"^(help|help me|what can (you do|i say|i do)|what commands( are there)?|"
                     r"(show|list)( me)?( all)?( the)? commands|commands)$", re.I)


def is_help(text: str) -> bool:
    return bool(HELP_RE.match(" ".join(text.strip().strip(".!?").split())))


def capabilities(kb: Knowledge, language: str = "en") -> dict[str, Any]:
    apps = [kb.display(a, "en") for a in kb.apps]
    pretty = {"youtube": "YouTube", "github": "GitHub", "gmail": "Gmail"}
    sites = [pretty.get(s, s.title()) for s in kb.sites]
    groups: list[dict[str, Any]] = [
        {"id": "apps", "title": "Open apps", "hint": "Only apps on the allowed list",
         "examples": [f"Open {name}" for name in apps]},
        {"id": "sites", "title": "Open websites", "hint": "Only allowed websites",
         "examples": [f"Open {s}" for s in sites]},
        {"id": "search", "title": "Search & browse", "hint": "Runs in the agent browser on PC2 and reuses its tab",
         "examples": ["Search for weather in Bangkok", "Look up python asyncio", "Search lofi on YouTube",
                      "Open the first result", "Open result 2"]},
        {"id": "music", "title": "Music & video",
         "hint": "YouTube plays in the agent browser; keys also control Spotify",
         "examples": ["Play lofi hip hop", "Play bodyslam on YouTube", "Pause the music", "Resume",
                      "Next song", "Previous song"]},
        {"id": "volume", "title": "Volume", "hint": "1 step ≈ 2 %",
         "examples": ["Volume up 20%", "Turn the volume down", "Louder", "Quieter", "Mute"]},
        {"id": "tabs", "title": "Browser tabs", "hint": "Tabs of the agent browser",
         "examples": ["Next tab", "Previous tab", "Close this tab", "What tabs are open?"]},
        {"id": "pc", "title": "Computer", "hint": "Stop works at any time",
         "examples": ["Status", "What's running on the PC?", "Stop everything", "Wake up the PC", "Help"]},
        {"id": "screen", "title": "Screen", "hint": "The local AI looks at PC2's screen; the picture is not kept",
         "examples": ["What's on the screen?", "Describe the screen"]},
        *([{"id": "code", "title": "Code projects",
            "hint": "AI edits happen on an ai/… git branch; main is never touched",
            "examples": [f"Run the tests in {p}", f"Show the diff for {p}", f"Revert the changes in {p}"]}
           for p in list(kb.projects)[:1]]),
        {"id": "ai", "title": "Just ask naturally", "hint": "The local AI works out what you mean",
         "examples": ["I need to do some math", "I'd like to write some notes", "Take me to GitHub",
                      "It's too loud, turn it down a bit",
                      *[f"In the {p} project, add a function multiply to calc.py" for p in list(kb.projects)[:1]]]},
    ]
    return {
        "language": language,
        "english_only": language == "en",
        "groups": groups,
        "apps": apps,
        "sites": sites,
        "refused": ["Commands in other languages" if language == "en" else "Apps/sites not on the lists",
                    "Apps or websites not on the allowed lists", "Deleting files or changing system settings",
                    "Running shell / PowerShell commands", "Payments, passwords, posting on social media",
                    "Solving CAPTCHAs (the agent stops and tells you)"],
    }


def help_summary(kb: Knowledge, language: str = "en") -> str:
    apps = ", ".join(kb.display(a, "en") for a in kb.apps)
    if language == "th":
        return (f"สั่งได้: เปิดแอป ({apps}), เปิดเว็บ, ค้นหา, เล่นเพลง YouTube, เพลงถัดไป, เพิ่ม/ลดเสียง, "
                "จัดการแท็บ, สถานะ, หยุด — ดูทั้งหมดที่ปุ่ม “All commands”")
    return (f"You can: open apps ({apps}), open websites, search the web or YouTube, play music, "
            "next/previous song, volume, browser tabs, status and stop. Tap “All commands” for the full list.")
