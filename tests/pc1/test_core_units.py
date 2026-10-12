"""Unit tests: state machine, aliases, shortcuts, policy (bottom of the test pyramid, §18.1)."""
from __future__ import annotations

import pytest

from app.core.aliases import AliasNormalizer
from app.core.jobs import InvalidTransition, Job, JobState
from app.core.policy import PolicyContext, RateLimiter, decide
from app.core.shortcuts import match_shortcut
from voice_contracts.models import ToolCall
from voice_contracts.tools import args_hash, llm_tool_schemas

S = JobState


# ---------------------------------------------------------------- state machine (§14.3)
def test_happy_path_transitions():
    job = Job(id="j1", device="d", source="audio")
    for s in [S.TRANSCRIBING, S.PLANNING, S.ROUTING, S.DISPATCHING, S.RUNNING, S.VERIFYING, S.DONE]:
        job.transition(s)
    assert job.terminal


@pytest.mark.parametrize("start,bad", [(S.CREATED, S.RUNNING), (S.PLANNING, S.DISPATCHING),
                                       (S.ROUTING, S.RUNNING), (S.AWAITING_CONFIRM, S.RUNNING)])
def test_illegal_transitions_rejected(start, bad):
    job = Job(id="j1", device="d", source="text", state=start)
    with pytest.raises(InvalidTransition):
        job.transition(bad)


@pytest.mark.parametrize("terminal", [S.DONE, S.FAILED, S.CANCELLED])
def test_terminal_states_are_final(terminal):
    job = Job(id="j1", device="d", source="text", state=terminal)
    with pytest.raises(InvalidTransition):
        job.transition(S.PLANNING)


def test_any_active_state_can_fail_or_cancel():
    for s in S:
        if s in (S.DONE, S.FAILED, S.CANCELLED):
            continue
        Job(id="a", device="d", source="text", state=s).transition(S.FAILED)
        Job(id="b", device="d", source="text", state=s).transition(S.CANCELLED)


def test_job_roundtrip():
    job = Job(id="j1", device="d", source="text", text="x")
    assert Job.from_dict(job.to_dict()) == job


# ---------------------------------------------------------------- aliases (US-203 / TC-F06)
ALIAS_CASES = [
    ("เปิดสปอติฟาย", "spotify"), ("เปิดสปอทิฟาย", "spotify"), ("เปิด สะปอติฟาย หน่อย", "spotify"),
    ("เปิดโครมให้หน่อย", "chrome"), ("เปิดกูเกิลโครม", "chrome"), ("เปิด Google Chrome", "chrome"),
    ("เปิดโน้ตแพด", "notepad"), ("เปิดโน๊ตแพด", "notepad"), ("เปิดโน้ตแพ็ด", "notepad"),
    ("เปิด Notepad", "notepad"), ("เปิดเครื่องคิดเลข", "calculator"), ("เปิดแคลคูเลเตอร์", "calculator"),
    ("เปิดยูทูบ", "youtube"), ("เปิดยูทูป", "youtube"), ("เปิด YouTube", "youtube"),
    ("เปิดเคอร์เซอร์", "cursor"), ("เปิดวีเอสโค้ด", "vscode"), ("เปิด VS Code", "vscode"),
    ("เปิดกิตฮับ", "github"), ("เปิดเฟสบุ๊ค", "facebook"),
]


def test_alias_mapping_accuracy_tc_f06(kb):
    norm = AliasNormalizer(kb.aliases, [*kb.apps, *kb.sites])
    hits = sum(1 for text, want in ALIAS_CASES if want in norm(text).split())
    assert len(ALIAS_CASES) == 20
    assert hits / len(ALIAS_CASES) >= 0.95, f"{hits}/20"


def test_alias_normalizer_collapses_whitespace(kb):
    norm = AliasNormalizer(kb.aliases, list(kb.apps))
    assert norm("  เปิด   โครม  ") == "เปิด chrome"


# ---------------------------------------------------------------- shortcuts (level 1)
@pytest.mark.parametrize("text,tool,args", [
    ("เปิด chrome ให้หน่อย", "open_app", {"app": "chrome"}),
    ("เปิด notepad", "open_app", {"app": "notepad"}),
    ("เปิดโปรแกรม spotify ครับ", "open_app", {"app": "spotify"}),
    ("เปิด youtube", "open_url", {"url": "https://www.youtube.com/"}),
    ("หยุดก่อน", "stop_all", {}),
    ("หยุด", "stop_all", {}),
    ("สถานะเครื่อง", "get_status", {}),
])
def test_shortcut_matches(kb, text, tool, args):
    call = match_shortcut(text, kb)
    assert call is not None and call.tool == tool and call.arguments == args


@pytest.mark.parametrize("text", [
    "เปิด chrome แล้วค้นหาวิธีติดตั้ง docker",  # needs planning
    "เปิด regedit",  # unknown target
    "เปิดมัน",  # ambiguous
    "เปิด chrome กับ notepad",  # two targets
    "ปิด chrome",
])
def test_shortcut_defers_to_llm(kb, text):
    assert match_shortcut(text, kb) is None


# ---------------------------------------------------------------- policy (deny by default)
def ctx(kb, **kw):
    return PolicyContext(kb, **kw)


def test_allow_open_app_with_hash(kb):
    d = decide(ToolCall(tool="open_app", arguments={"app": "chrome"}), ctx(kb))
    assert d.decision == "allow" and d.risk == 1
    assert d.args_hash == args_hash("open_app", {"app": "chrome"})


def test_unknown_tool_denied(kb):
    assert decide(ToolCall(tool="run_shell", arguments={"cmd": "dir"}), ctx(kb)).decision == "deny"


def test_tc_f05_app_outside_allowlist_denied(kb):
    d = decide(ToolCall(tool="open_app", arguments={"app": "regedit"}), ctx(kb))
    assert d.decision == "deny" and d.reason == "app not in allowlist"


@pytest.mark.security
@pytest.mark.parametrize("app", ["notepad; del *", "notepad && calc", "../../cmd", "a" * 500,
                                 "chrome\u202e", "CHROME.EXE", "", "ｃｈｒｏｍｅ"])
def test_tc_s05_s06_injection_and_weird_values_denied(kb, app):
    d = decide(ToolCall(tool="open_app", arguments={"app": app}), ctx(kb))
    assert d.decision == "deny"


def test_extra_arguments_denied(kb):
    d = decide(ToolCall(tool="open_app", arguments={"app": "chrome", "args": "--evil"}), ctx(kb))
    assert d.decision == "deny" and d.reason.startswith("bad args")


@pytest.mark.parametrize("url,ok", [
    ("https://www.youtube.com/watch?v=x", True),
    ("https://youtube.com/", True),
    ("http://www.youtube.com/", False),
    ("https://evil-youtube.com/", False),
    ("https://youtube.com.evil.org/", False),
    ("https://user:pw@youtube.com/", False),
    ("javascript:alert(1)", False),
    ("file:///C:/Windows/System32", False),
])
def test_tc_f23_url_rules(kb, url, ok):
    d = decide(ToolCall(tool="open_url", arguments={"url": url}), ctx(kb))
    assert (d.decision == "allow") is ok


@pytest.mark.security
def test_tc_s11_rate_limit(kb):
    rate = RateLimiter(limit=5, clock=lambda: 1000.0)
    c = ctx(kb, rate=rate)
    results = [decide(ToolCall(tool="open_app", arguments={"app": "notepad"}), c).decision
               for _ in range(100)]
    assert results.count("allow") == 5 and results.count("deny") == 95
    # Stop/status keep working while rate limited.
    assert decide(ToolCall(tool="stop_all"), c).decision == "allow"


def test_kill_switch_blocks_actions_not_stop(kb):
    c = ctx(kb, kill_switch=True)
    assert decide(ToolCall(tool="open_app", arguments={"app": "chrome"}), c).decision == "deny"
    assert decide(ToolCall(tool="stop_all"), c).decision == "allow"


def test_high_risk_and_taint_require_confirm(kb, risky_tool):
    call = ToolCall(tool="send_message", arguments={"to": "a", "text": "hi"})
    assert decide(call, ctx(kb)).decision == "confirm"
    assert decide(call, ctx(kb, tainted=True)).decision == "confirm"
    # Low-risk tool after reading untrusted content still runs (risk 1 < 2).
    assert decide(ToolCall(tool="open_app", arguments={"app": "chrome"}), ctx(kb, tainted=True)).decision == "allow"


def test_llm_schema_has_allowlist_enum():
    schemas = {s["function"]["name"]: s for s in llm_tool_schemas(["chrome", "notepad"])}
    app = schemas["open_app"]["function"]["parameters"]["properties"]["app"]
    assert app["enum"] == ["chrome", "notepad"]



def test_whisper_repetition_is_collapsed():
    from app.adapters.faster_whisper_stt import collapse_repeats
    assert collapse_repeats("Skip ad, skip ad, skip ad.") == "Skip ad."
    assert collapse_repeats("pause the music, " * 40 + "pause the music") == "pause the music."
    assert collapse_repeats("Open Chrome. Play lofi.") == "Open Chrome. Play lofi."
