"""Hands-free wake-word filter (Phase 4, doc §S11–S14).

The phone streams short speech segments (client-side VAD). Every segment is transcribed, and only these
become commands:
  - "computer, open chrome"        -> command "open chrome"
  - "computer"                     -> wake only: the phone listens for the next sentence without the word
  - "stop" while a job is running  -> stop (stopping must never need the wake word)
  - anything after a bare wake     -> command (armed window)
Everything else is ignored and NOT stored: room conversation must never turn into jobs or logs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .i18n import is_english

DEFAULT_WAKE_WORDS = ("computer",)
STOP_PHRASES = frozenset({"stop", "stop it", "stop now", "stop stop", "stop everything", "cancel", "halt",
                          "stop all", "stop that"})


@dataclass(frozen=True)
class WakeDecision:
    kind: str  # "command" | "wake_only" | "ignore"
    command: str = ""


def _clean(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", text.lower()).split())


def wake_filter(text: str, wake_words: tuple[str, ...] = DEFAULT_WAKE_WORDS, armed: bool = False,
                job_active: bool = False) -> WakeDecision:
    if not text.strip() or not is_english(text):
        return WakeDecision("ignore")
    cleaned = _clean(text)
    if not cleaned:
        return WakeDecision("ignore")
    for w in wake_words:
        m = re.match(rf"^\W*(?:(?:hey|ok|okay|hi)\W+)?{re.escape(w)}\b[\W_]*", text, re.I)
        if m:
            rest = text[m.end():].strip()
            return WakeDecision("command", rest) if _clean(rest) else WakeDecision("wake_only")
    if cleaned in STOP_PHRASES and job_active:
        return WakeDecision("command", "stop")
    if armed:
        return WakeDecision("command", text.strip())
    return WakeDecision("ignore")
