"""App flows (redesign step 1): wizard definitions, answer checking, voice triggers, API."""
from __future__ import annotations

import pytest

from app.core.flows import FLOWS, FlowError, control_command, flow_trigger, public_flows, resolve
from app.core.jobs import JobState
from app.core.shortcuts import match_shortcut

S = JobState
QUERY = "lofi hip hop"


def _answers_for(flow, kb):
    """Every combination of available choices (text stages get QUERY)."""
    combos = [{}]
    stages = next(f for f in public_flows(kb, lambda k: None) if f["id"] == flow)["stages"]
    for st in stages:
        nxt = []
        for a in combos:
            if st["when"] and a.get(st["when"]["stage"]) not in st["when"]["values"]:
                nxt.append(a)
                continue
            if st["kind"] == "text":
                nxt.append({**a, st["id"]: QUERY})
            else:
                nxt += [{**a, st["id"]: o["value"]} for o in st["options"] if o["available"]]
        combos = nxt
    return combos


EXPECTED = {"youtube": {"youtube_play", "web_search"}, "music": {"youtube_play"}, "search": {"web_search"},
            "apps": {"open_app"}}


@pytest.mark.parametrize("flow", ["youtube", "music", "search", "apps"])
def test_every_flow_answer_becomes_a_real_tool_call(kb, rig, flow):
    """Like the quick-action cards: a wizard must never send a sentence the parser misreads."""
    for answers in _answers_for(flow, kb):
        command, _ = resolve(flow, answers, kb)
        if command is None:
            continue
        call = match_shortcut(rig.orch.normalize(command), kb)
        assert call is not None and call.tool in EXPECTED[flow], (answers, command, call)
        if "query" in answers:
            assert call.arguments.get("query") == QUERY


def test_code_flow_open_is_a_shortcut_and_change_goes_to_the_coding_loop(kb, rig):
    from app.core.orchestrator import mentioned_project
    cmd, remember = resolve("code", {"what": "open", "project": "demo"}, kb)
    assert match_shortcut(rig.orch.normalize(cmd), kb).tool == "open_project"
    assert remember == {"flow.last_project": "demo"}
    cmd, _ = resolve("code", {"what": "change", "project": "demo", "request": "add a subtract function"}, kb)
    assert mentioned_project(rig.orch.normalize(cmd), kb) == "demo"


def test_every_control_parses(kb, rig):
    answers = {"project": "demo"}
    expected = {"code": {"git_diff", "run_tests", "revert_changes"}}
    for f in FLOWS.values():
        for i, _c in enumerate(f.controls):
            cmd = control_command(f.id, i, answers, kb)
            call = match_shortcut(rig.orch.normalize(cmd), kb)
            assert call is not None, (f.id, cmd)
            assert call.tool in expected.get(f.id, {call.tool}), (f.id, cmd, call.tool)


@pytest.mark.parametrize("flow,answers,msg", [
    ("youtube", {"what": "dance"}, "choose"),
    ("youtube", {"what": "play", "query": "   "}, "needs an answer"),
    ("code", {"what": "change", "project": "secret-repo", "request": "x"}, "choose"),
    ("code", {"what": "new", "project": "demo"}, "choose"),  # not available until build step 3
    ("music", {"app": "tiktok", "query": "x"}, "choose"),
    ("apps", {"app": "regedit"}, "choose"),
    ("facebook", {}, "unknown flow"),
    ("nope", {}, "unknown flow"),
])
def test_bad_answers_are_rejected(kb, flow, answers, msg):
    with pytest.raises(FlowError, match=msg):
        resolve(flow, answers, kb)


def test_control_placeholders_only_take_checked_values(kb):
    with pytest.raises(FlowError):
        control_command("code", 0, {"project": "../../etc"}, kb)
    with pytest.raises(FlowError):
        control_command("youtube", 99, {}, kb)


@pytest.mark.parametrize("text,flow", [
    ("YouTube", "youtube"), ("open YouTube", "youtube"), ("Open Cursor.", "code"), ("open the code app", "code"),
    ("search", "search"), ("music", "music"),
])
def test_spoken_app_names_open_the_wizard(text, flow):
    assert flow_trigger(text) == flow


@pytest.mark.parametrize("text", ["search cats", "play lofi", "open notepad", "stop", "open facebook",
                                  "in the demo project open the code"])
def test_other_commands_are_not_flow_triggers(text):
    assert flow_trigger(text) is None


async def test_voice_trigger_finishes_on_pc1_without_touching_pc2(rig):
    job = await rig.run_text("Open YouTube")
    assert job.state == S.DONE and job.flow == "youtube" and job.planner == "flow" and rig.pc2.calls == []


async def test_remember_last_used_becomes_the_default(rig, kb):
    job = await rig.orch.run_flow("music", {"app": "youtube", "query": "lofi"}, "phone")
    await rig.orch.wait_idle()
    assert rig.orch.get_job(job.id).flow == "music"
    music = next(f for f in rig.orch.flows() if f["id"] == "music")
    assert music["stages"][0]["default"] == "youtube"


def test_flow_api(api):
    client, rig, _ = api
    flows = client.get("/flows").json()
    ids = {f["id"]: f for f in flows}
    assert ids["youtube"]["available"] and not ids["facebook"]["available"] and ids["facebook"]["coming"]
    project = next(s for s in ids["code"]["stages"] if s["id"] == "project")
    assert [o["value"] for o in project["options"]] == ["demo"]
    r = client.post("/flows/youtube/run", json={"answers": {"what": "play", "query": "lofi"}})
    assert r.status_code == 200 and r.json()["job"]["text"] == "play lofi" and r.json()["job"]["flow"] == "youtube"
    assert client.post("/flows/youtube/run", json={"answers": {"what": "controls"}}).json() == {"job": None}
    assert client.post("/flows/youtube/run", json={"answers": {"what": "hack"}}).status_code == 422
    r = client.post("/flows/youtube/control", json={"index": 1, "answers": {}})
    assert r.status_code == 200 and r.json()["text"] == "Next song"
    assert client.post("/flows/youtube/control", json={"index": 19, "answers": {}}).status_code == 422


def test_stt_endpoint_returns_text_and_creates_no_job(api):
    client, rig, _ = api
    rig.stt.text = "the second one"
    before = len(client.get("/jobs").json())
    r = client.post("/stt", files={"audio": ("a.webm", b"\x1a\x45", "audio/webm")})
    assert r.status_code == 200 and r.json() == {"text": "the second one"}
    assert len(client.get("/jobs").json()) == before
    assert client.post("/stt", files={"audio": ("a.txt", b"x", "text/plain")}).status_code == 415
