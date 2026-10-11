"""Phase 3 multi-step coding loop (US-506, TC-F16) with a scripted LLM and a fake PC2."""
from __future__ import annotations

import pytest

from app.adapters.fakes import ScriptedLLM
from app.core.jobs import JobState
from app.core.shortcuts import match_shortcut
from app.ports import PlanResult
from voice_contracts.models import ToolResult
from voice_contracts.tools import llm_tool_schemas

S = JobState


def coding_pc2(rig, test_results):
    """Fake PC2 coding tools; run_tests returns the given pass/fail sequence."""
    results = iter(test_results)
    h = rig.pc2.handlers
    h["read_file"] = lambda a: ToolResult(ok=True, verified=True, data={"content": "def add(a, b):\n    return a+b\n",
                                                                         "lines": 2})
    h["edit_file"] = lambda a: ToolResult(ok=True, verified=True, data={"branch": "ai/20261012-1", "path": a["path"],
                                                                         "stat": "1 file changed"})
    h["run_tests"] = lambda a: ToolResult(ok=True, verified=True, data={"passed": next(results), "exit_code": 0,
                                                                         "output_tail": "1 failed", "duration_s": 1})
    h["git_diff"] = lambda a: ToolResult(ok=True, verified=True, data={"files": ["calc.py"], "branch": "ai/x",
                                                                        "base": "main", "stat": "1 file"})


def tool(name, **args):
    return ScriptedLLM.tool(name, **args)


async def test_code_task_reads_edits_tests_fixes_and_reports(rig_factory):
    rig = rig_factory(language="en")
    coding_pc2(rig, [False, True])
    rig.llm.script = [
        tool("read_file", project="demo", path="calc.py"),
        tool("edit_file", project="demo", path="calc.py", old_text="return a+b", new_text="return a + b"),
        tool("run_tests", project="demo"),
        tool("edit_file", project="demo", path="calc.py", old_text="return a + b", new_text="return int(a) + int(b)"),
        tool("run_tests", project="demo"),
        PlanResult(kind="final", message="Made add() accept strings"),
    ]
    job = await rig.run_text("in the demo project make add accept numeric strings")
    assert job.state == S.DONE and len(job.steps) == 5
    assert [s["tool"] for s in job.steps] == ["read_file", "edit_file", "run_tests", "edit_file", "run_tests"]
    assert job.summary.startswith("Made add() accept strings. 2 edit(s) on branch ai/20261012-1 (calc.py); "
                                  "tests PASSED")
    assert "revert the changes in demo" in job.summary
    assert rig.llm.calls[-1][1].observations[-1]["tool"] == "run_tests"  # the model saw the test result


async def test_model_cannot_claim_success_when_tests_failed(rig_factory):
    """LLM09: the verdict comes from run_tests, not from the model's DONE message."""
    rig = rig_factory(language="en")
    coding_pc2(rig, [False])
    rig.llm.script = [
        tool("edit_file", project="demo", path="calc.py", old_text="a", new_text="b"),
        tool("run_tests", project="demo"),
        PlanResult(kind="final", message="All tests pass now"),
    ]
    job = await rig.run_text("fix the bug in demo")
    assert job.summary.startswith("Not finished — All tests pass now") and "tests FAILED" in job.summary


async def test_coding_loop_is_bounded(rig_factory):
    rig = rig_factory(language="en", coding_max_steps=4)
    coding_pc2(rig, [False] * 10)
    n = iter(range(100))
    rig.llm.script = lambda text, ctx: tool("read_file", project="demo", path=f"f{next(n)}.py")
    job = await rig.run_text("refactor everything in demo")
    assert job.state == S.FAILED and len(job.steps) == 4 and "loop guard" in job.error.lower()


async def test_non_coding_llm_jobs_stay_single_step(rig_factory):
    rig = rig_factory(language="en")
    rig.llm.script = [tool("open_app", app="notepad"), tool("open_app", app="chrome")]
    job = await rig.run_text("I'd like to write some notes")
    assert job.state == S.DONE and len(job.steps) == 1 and len(rig.llm.calls) == 1


async def test_unknown_project_denied(rig_factory):
    rig = rig_factory(language="en")
    rig.llm.script = [tool("read_file", project="secret-repo", path="x.py")]
    job = await rig.run_text("read x.py in secret-repo")
    assert job.state == S.FAILED and job.outcome == "denied" and rig.pc2.calls == []


def test_project_tools_only_offered_when_projects_exist():
    names = lambda tools: {t["function"]["name"] for t in tools}  # noqa: E731
    assert "edit_file" not in names(llm_tool_schemas(["chrome"], []))
    schemas = {t["function"]["name"]: t for t in llm_tool_schemas(["chrome"], ["demo"])}
    assert schemas["edit_file"]["function"]["parameters"]["properties"]["project"]["enum"] == ["demo"]


@pytest.mark.parametrize("text,tool_name", [
    ("open project demo", "open_project"), ("Open the demo project", "open_project"),
    ("list files in demo", "list_files"), ("run the tests in demo", "run_tests"), ("test demo", "run_tests"),
    ("show the diff for demo", "git_diff"), ("what changed in demo", "git_diff"),
    ("revert the changes in demo", "revert_changes"), ("undo the AI changes in the demo project", "revert_changes"),
    ("git status of demo", "git_status"),
])
def test_project_shortcuts(kb, rig, text, tool_name):
    call = match_shortcut(rig.orch.normalize(text), kb)
    assert call is not None and call.tool == tool_name and call.arguments == {"project": "demo"}


def test_unregistered_project_name_goes_to_planner(kb, rig):
    assert match_shortcut(rig.orch.normalize("run the tests in gymmate"), kb) is None


def test_planner_sees_its_own_previous_calls_and_progress():
    """Small models repeat a step unless they see their earlier call (live bug: open_project twice)."""
    from app.adapters.ollama_llm import OllamaLLM
    from app.ports import PlanContext

    llm = OllamaLLM.__new__(OllamaLLM)
    llm.language = "en"
    obs = [{"tool": "read_file", "arguments": {"project": "demo", "path": "calc.py"},
            "result": {"ok": True, "data": {"content": "x"}}, "trusted": True},
           {"tool": "run_tests", "arguments": {"project": "demo"},
            "result": {"ok": True, "data": {"passed": False}}, "trusted": True}]
    msgs = llm._messages("fix divide in demo", PlanContext(knowledge_summary="", tools=[], observations=obs))
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "tool", "user"]
    assert msgs[2]["tool_calls"][0]["function"] == {"name": "read_file",
                                                     "arguments": {"project": "demo", "path": "calc.py"}}
    assert "1. read_file calc.py -> ok" in msgs[-1]["content"] and "2. run_tests -> tests FAILED" in msgs[-1]["content"]
