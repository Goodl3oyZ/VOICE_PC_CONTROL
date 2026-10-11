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
    h["list_files"] = lambda a: ToolResult(ok=True, verified=True, data={"files": ["calc.py", "test_calc.py"]})
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
    assert job.state == S.DONE and len(job.steps) == 6
    assert [s["tool"] for s in job.steps] == ["list_files", "read_file", "edit_file", "run_tests", "edit_file",
                                              "run_tests"]
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


async def test_naming_a_project_fetches_files_first_and_offers_only_coding_tools(rig_factory):
    """G3 run: the model opened Cursor (open_app) or guessed file names; now step 1 is list_files."""
    rig = rig_factory(language="en")
    coding_pc2(rig, [True])
    rig.pc2.handlers["list_files"] = lambda a: ToolResult(ok=True, verified=True, data={"files": ["calc.py"]})
    rig.llm.script = [tool("edit_file", project="demo", path="calc.py", old_text="", new_text="def f(): pass"),
                      tool("run_tests", project="demo"), PlanResult(kind="final", message="Added f")]
    job = await rig.run_text("In the demo project, add a function f")
    assert [s["tool"] for s in job.steps] == ["list_files", "edit_file", "run_tests"] and job.state == S.DONE
    offered = {t["function"]["name"] for t in rig.llm.calls[0][1].tools}
    assert "open_app" not in offered and "edit_file" in offered and "revert_changes" not in offered


async def test_coding_tool_error_is_feedback_not_failure(rig_factory):
    rig = rig_factory(language="en")
    coding_pc2(rig, [True])
    rig.pc2.handlers["read_file"] = lambda a: (
        ToolResult(ok=False, error="file not found: calculator.py") if a["path"] == "calculator.py"
        else ToolResult(ok=True, verified=True, data={"content": "x", "lines": 1}))
    rig.llm.script = [tool("read_file", project="demo", path="calculator.py"),
                      tool("read_file", project="demo", path="calc.py"),
                      tool("run_tests", project="demo"), PlanResult(kind="final", message="checked")]
    job = await rig.run_text("in demo check calc")
    assert job.state == S.DONE and [s["result"]["ok"] for s in job.steps][1:3] == [False, True]
    assert rig.llm.calls[1][1].observations[-1]["result"]["error"] == "file not found: calculator.py"


async def test_steps_of_a_coding_job_do_not_hit_the_command_rate_limit(rig_factory):
    from app.core.policy import RateLimiter
    rig = rig_factory(language="en")
    rig.orch.rate = RateLimiter(limit=2)
    coding_pc2(rig, [True])
    rig.llm.script = [tool("read_file", project="demo", path=f"f{i}.py") for i in range(4)] + [
        PlanResult(kind="final", message="read")]
    job = await rig.run_text("in demo read some files")
    assert job.state == S.DONE and len(job.steps) == 5  # list_files + 4 reads, limit was 2


async def test_first_mid_task_question_is_answered_by_pc1(rig_factory):
    """G3 run 3: after failing tests the model asked "what should I do?" instead of fixing the code."""
    from app.adapters.ollama_llm import OllamaLLM
    from app.ports import PlanContext

    rig = rig_factory(language="en")
    coding_pc2(rig, [False, True])
    rig.llm.script = [tool("edit_file", project="demo", path="calc.py", old_text="a", new_text="b"),
                      tool("run_tests", project="demo"),
                      PlanResult(kind="clarify", message="Tests failed. What should I do?"),
                      tool("edit_file", project="demo", path="calc.py", old_text="b", new_text="c"),
                      tool("run_tests", project="demo"),
                      PlanResult(kind="final", message="Fixed")]
    job = await rig.run_text("in demo fix it")
    assert job.state == S.DONE and "tests PASSED" in job.summary, (job.error, job.summary)
    ctx: PlanContext = rig.llm.calls[3][1]
    assert ctx.history[0]["auto"] == "1"
    llm = OllamaLLM.__new__(OllamaLLM)
    llm.language = "en"
    msgs = llm._messages("in demo fix it", ctx)
    assert msgs[-1]["role"] == "user" and "keep all existing functions" in msgs[-1]["content"]

    rig2 = rig_factory(language="en")
    coding_pc2(rig2, [False])
    rig2.llm.script = [tool("run_tests", project="demo"), PlanResult(kind="clarify", message="Q1?"),
                       PlanResult(kind="clarify", message="Q2?")]
    job2 = await rig2.run_text("in demo do something")
    assert job2.state == S.CLARIFYING and job2.question == "Q2?"  # a second question reaches the user
    await rig2.orch.cancel(job2.id, "phone")
