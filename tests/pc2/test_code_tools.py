"""Phase 3 coding tools against a REAL temporary git repository (US-501..505, TC-F13..F15, TC-S04)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from agent.browser import FakeBrowser
from agent.config import AgentConfig
from agent.launcher import FakeLauncher
from agent.server import create_app
from voice_contracts.signing import signed_headers

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
SECRET = b"test-secret-0123456789-abcdefghijklmnop"
CALC = "def add(a, b):\n    return a + b\n"
TEST = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "demo"
    r.mkdir()
    (r / "calc.py").write_text(CALC)
    (r / "test_calc.py").write_text(TEST)
    git(r, "init", "-q", "-b", "main")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return r


@pytest.fixture
def agent(tmp_path, repo):
    cfg = AgentConfig.from_dict({
        "apps": {"cursor": {"process": "Cursor.exe", "argv": ["cursor.exe"]}},
        "projects": {"demo": {"path": str(repo), "test_cmd": [sys.executable, "-m", "pytest", "-q", "-p",
                                                               "no:cacheprovider"], "ide": "cursor"}},
        "allowed_clients": ["testclient"], "data_dir": str(tmp_path / "agent"), "verify_timeout_s": 0.2})
    launcher = FakeLauncher()
    launcher.process_for_argv0 = {"cursor.exe": "Cursor.exe"}
    with TestClient(create_app(cfg, SECRET, launcher, sleep=lambda s: None, browser=FakeBrowser())) as c:
        yield c, launcher


def call(client, tool, payload):
    body = json.dumps(payload).encode()
    path = f"/tool/{tool}"
    return client.post(path, content=body, headers=signed_headers(SECRET, "POST", path, body)).json()


def test_read_only_tools(agent):
    client, launcher = agent
    assert call(client, "open_project", {"project": "demo"})["verified"]
    assert launcher.launched[0][0] == "cursor.exe" and launcher.launched[0][1].endswith("demo")
    files = call(client, "list_files", {"project": "demo"})["data"]["files"]
    assert "calc.py" in files and not any(".git" in f for f in files)
    r = call(client, "read_file", {"project": "demo", "path": "calc.py"})
    assert r["data"]["content"] == CALC and r["data"]["lines"] == 3
    m = call(client, "search_code", {"project": "demo", "query": "return a"})["data"]["matches"]
    assert m == [{"file": "calc.py", "line": 2, "text": "return a + b"}]
    assert call(client, "git_status", {"project": "demo"})["data"] == {"project": "demo", "branch": "main",
                                                                      "changed": []}


def test_edit_happens_on_ai_branch_and_main_is_untouched(agent, repo):
    """US-503 / TC-F13: first edit creates ai/*, checkpoint commit there, main never changes."""
    client, _ = agent
    main_before = git(repo, "rev-parse", "main")
    r = call(client, "edit_file", {"project": "demo", "path": "calc.py", "old_text": "return a + b",
                                   "new_text": "return a + b  # sum"})
    assert r["ok"] and r["verified"] and r["data"]["branch"].startswith("ai/")
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").startswith("ai/")
    assert git(repo, "rev-parse", "main") == main_before
    assert git(repo, "status", "--porcelain") == ""  # checkpoint committed
    r = call(client, "edit_file", {"project": "demo", "path": "util.py", "old_text": "", "new_text": "X = 1\n"})
    assert r["data"]["created"] and (repo / "util.py").read_text() == "X = 1\n"


def test_edit_requires_exact_unique_text(agent, repo):
    client, _ = agent
    assert "not found" in call(client, "edit_file", {"project": "demo", "path": "calc.py", "old_text": "nope",
                                                     "new_text": "x"})["error"]
    (repo / "dup.py").write_text("a\na\n")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "dup")
    assert "2 times" in call(client, "edit_file", {"project": "demo", "path": "dup.py", "old_text": "a",
                                                   "new_text": "b"})["error"]
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"  # nothing changed, no branch created


def test_refuses_to_touch_uncommitted_user_work(agent, repo):
    client, _ = agent
    (repo / "calc.py").write_text(CALC + "# my unsaved work\n")
    r = call(client, "edit_file", {"project": "demo", "path": "calc.py", "old_text": "return a + b",
                                   "new_text": "return b + a"})
    assert "uncommitted changes" in r["error"] and "my unsaved work" in (repo / "calc.py").read_text()


def test_run_tests_reports_pass_and_failure_honestly(agent):
    """US-504 / TC-F14: a failing test is reported as failed, never as success."""
    client, _ = agent
    r = call(client, "run_tests", {"project": "demo"})
    assert r["ok"] and r["data"]["passed"] is True
    call(client, "edit_file", {"project": "demo", "path": "calc.py", "old_text": "return a + b",
                               "new_text": "return a - b"})
    r = call(client, "run_tests", {"project": "demo"})
    assert r["data"]["passed"] is False and r["data"]["exit_code"] != 0 and "assert" in r["data"]["output_tail"]


def test_diff_and_revert_restore_everything(agent, repo):
    """US-505 / TC-F15: revert -> files back, ai branch deleted, main unchanged."""
    client, _ = agent
    main_before = git(repo, "rev-parse", "main")
    assert call(client, "git_diff", {"project": "demo"})["data"]["note"] == "no AI changes"
    call(client, "edit_file", {"project": "demo", "path": "calc.py", "old_text": "return a + b",
                               "new_text": "return a * b"})
    call(client, "edit_file", {"project": "demo", "path": "new.py", "old_text": "", "new_text": "Y = 2\n"})
    d = call(client, "git_diff", {"project": "demo"})["data"]
    assert set(d["files"]) == {"calc.py", "new.py"} and "-    return a + b" in d["diff"] and d["base"] == "main"
    r = call(client, "revert_changes", {"project": "demo"})
    assert r["verified"] and r["data"]["base_unchanged"]
    assert (repo / "calc.py").read_text() == CALC and not (repo / "new.py").exists()
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main" and git(repo, "rev-parse", "main") == main_before
    assert "ai/" not in git(repo, "branch")
    assert call(client, "revert_changes", {"project": "demo"})["data"]["note"] == "nothing to revert"


@pytest.mark.security
@pytest.mark.parametrize("tool,payload", [
    ("read_file", {"project": "demo", "path": "../secret.txt"}),
    ("read_file", {"project": "demo", "path": "C:/Windows/win.ini"}),
    ("read_file", {"project": "demo", "path": "/etc/passwd"}),
    ("read_file", {"project": "demo", "path": ".git/config"}),
    ("edit_file", {"project": "demo", "path": "../../evil.py", "old_text": "", "new_text": "x"}),
    ("list_files", {"project": "demo", "subdir": ".."}),
    ("read_file", {"project": "other", "path": "calc.py"}),
    ("run_tests", {"project": "demo", "cmd": "rm -rf /"}),
])
def test_tc_s04_paths_and_projects_are_contained(agent, tool, payload, tmp_path):
    client, _ = agent
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    r = call(client, tool, payload)
    assert not r["ok"] and "TOP SECRET" not in json.dumps(r)


def test_empty_old_text_appends_to_existing_file(agent, repo):
    """Adding a function: small models can't produce an anchor, so '' means append (G3 run, task C10)."""
    client, _ = agent
    r = call(client, "edit_file", {"project": "demo", "path": "calc.py", "old_text": "",
                                   "new_text": "def multiply(a, b):\n    return a * b"})
    assert r["ok"] and r["data"]["appended"]
    assert (repo / "calc.py").read_text() == CALC + "\n\ndef multiply(a, b):\n    return a * b\n"


def test_whitespace_tolerant_unique_match(agent, repo):
    client, _ = agent
    r = call(client, "edit_file", {"project": "demo", "path": "calc.py",
                                   "old_text": "def add(a, b):\n  return a + b   ",  # wrong indentation/trailing
                                   "new_text": "def add(a, b):\n    return b + a\n"})
    assert r["ok"], r
    assert (repo / "calc.py").read_text() == "def add(a, b):\n    return b + a\n"


def test_crlf_files_keep_crlf(agent, repo):
    client, _ = agent
    (repo / "win.txt").write_bytes(b"one\r\ntwo\r\n")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "crlf")
    r = call(client, "edit_file", {"project": "demo", "path": "win.txt", "old_text": "two", "new_text": "2"})
    assert r["ok"] and (repo / "win.txt").read_bytes() == b"one\r\n2\r\n"

TWO = "def a():\n    return 1\n\n\ndef b():\n    return 2"
ONE_BLANK = "def a():\n    return 1\n\ndef b():\n    return 2"
C = "\n\n\ndef c():\n    return 3"


def test_match_tolerates_collapsed_blank_lines(agent, repo):
    """G3 run 2: the model sends the file with ONE blank line where the file has two (PEP 8)."""
    client, _ = agent
    (repo / "two.py").write_text(TWO + "\n")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "two")
    r = call(client, "edit_file", {"project": "demo", "path": "two.py", "old_text": ONE_BLANK, "new_text": TWO + C})
    assert r["ok"], r
    assert (repo / "two.py").read_text() == TWO + C + "\n"


def test_python_guardrails_block_deleting_functions_and_syntax_errors(agent, repo):
    """G3 run 3: 'add multiply' replaced divide; also never commit a file that doesn't parse."""
    client, _ = agent
    r = call(client, "edit_file", {"project": "demo", "path": "calc.py", "old_text": "def add(a, b):\n    return a + b",
                                   "new_text": "def multiply(a, b):\n    return a * b"})
    assert not r["ok"] and "would delete add" in r["error"] and (repo / "calc.py").read_text() == CALC
    r = call(client, "edit_file", {"project": "demo", "path": "calc.py", "old_text": "return a + b",
                                   "new_text": "return a +"})
    assert not r["ok"] and "not be valid Python" in r["error"]
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"  # nothing applied, no branch
    r = call(client, "edit_file", {"project": "demo", "path": "calc.py", "old_text": "def add(a, b):\n    return a + b",
                                   "new_text": "def plus(a, b):\n    return a + b", "allow_removing": True})
    assert r["ok"]  # an explicit rename is still possible



def test_double_escaped_quotes_are_accepted(agent, repo):
    """G3 runs 2 and 4: the model sent shout(...) + \\"!\\" (JSON-escaped twice)."""
    client, _ = agent
    (repo / "s.py").write_text('def shout(t):\n    return t.upper() + "!"\n')
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "s")
    r = call(client, "edit_file", {"project": "demo", "path": "s.py",
                                   "old_text": 'return t.upper() + \\"!\\"',
                                   "new_text": 'return t.upper() + \\"!!!\\"'})
    assert r["ok"], r
    assert (repo / "s.py").read_text() == 'def shout(t):\n    return t.upper() + "!!!"\n'


def test_wrong_indentation_is_repaired_when_that_makes_valid_python(agent, repo):
    """G3 run 4: a docstring edit came back with the wrong indentation (unexpected indent)."""
    client, _ = agent
    r = call(client, "edit_file", {"project": "demo", "path": "calc.py", "old_text": "def add(a, b):\n    return a + b",
                                   "new_text": "    def add(a, b):\n        \"\"\"Add.\"\"\"\n        return a + b"})
    assert r["ok"], r
    assert (repo / "calc.py").read_text() == 'def add(a, b):\n    """Add."""\n    return a + b\n'
