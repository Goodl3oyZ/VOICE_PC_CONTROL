"""The command guide must never advertise something that doesn't work."""
from __future__ import annotations

import pytest

from app.core.capabilities import capabilities, is_help
from app.core.jobs import JobState
from app.core.policy import PolicyContext, decide
from app.core.shortcuts import match_shortcut


def all_examples(kb):
    for g in capabilities(kb)["groups"]:
        for ex in g["examples"]:
            yield g["id"], ex


def test_every_listed_command_works(kb, rig):
    """Each example (except free-form AI ones and Help) must parse to a tool call the policy allows."""
    checked = 0
    for group, ex in all_examples(kb):
        if group == "ai" or is_help(ex):
            continue
        call = match_shortcut(rig.orch.normalize(ex), kb)
        assert call is not None, f"guide example does not parse: {ex!r}"
        d = decide(call, PolicyContext(kb))
        assert d.decision == "allow", f"guide example denied by policy: {ex!r} -> {d.reason}"
        checked += 1
    assert checked >= 30


def test_ai_examples_go_to_the_planner(kb, rig):
    for group, ex in all_examples(kb):
        if group == "ai":
            assert match_shortcut(rig.orch.normalize(ex), kb) is None, ex


def test_apps_and_sites_come_from_knowledge(kb):
    caps = capabilities(kb)
    assert "Calculator" in caps["apps"] and "Open Calculator" in caps["groups"][0]["examples"]
    assert "YouTube" in caps["sites"] and caps["english_only"] is True


@pytest.mark.parametrize("text,ok", [("Help", True), ("what can you do?", True), ("What can I say", True),
                                     ("show me all the commands", True), ("help me open chrome", False)])
def test_is_help(text, ok):
    assert is_help(text) is ok


async def test_help_command_answers_without_pc2(rig_factory):
    rig = rig_factory(language="en")
    job = await rig.run_text("What can I say?")
    assert job.state == JobState.DONE and job.planner == "help" and job.summary.startswith("You can:")
    assert rig.pc2.calls == [] and rig.llm.calls == []


def test_capabilities_endpoint(api):
    client, rig, _ = api
    caps = client.get("/capabilities").json()
    assert {g["id"] for g in caps["groups"]} >= {"apps", "search", "music", "volume", "tabs", "pc", "ai"}


def test_quick_actions_parse(kb, rig):
    """The PWA's quick-action cards must run real tools (a card once sent "Play or pause music", which
    searched YouTube for "or pause music", and another asked to lock the PC, which no tool can do)."""
    import re
    from pathlib import Path
    hero = Path(__file__).resolve().parents[2] / "mobile-pwa" / "src" / "components" / "MicrophoneHero.tsx"
    src = hero.read_text(encoding="utf-8")
    commands = re.findall(r'command: "([^"]+)"', src)
    assert len(commands) >= 4
    expected = {"Volume up 20%": "media_control", "Pause the music": "media_control", "Next song": "media_control",
                "What's on the screen?": "look_at_screen"}
    for c in commands:
        call = match_shortcut(rig.orch.normalize(c), kb)
        assert call is not None, f"quick action does not parse: {c!r}"
        assert call.tool == expected.get(c, call.tool), (c, call.tool)
        assert call.tool != "youtube_play", c
