"""Project discovery, confirm-once registration and new projects on PC2 (app flows step 3), real git."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.browser import FakeBrowser
from agent.config import AgentConfig
from agent.launcher import FakeLauncher
from agent.server import create_app
from agent.tools import projects
from voice_contracts.signing import signed_headers
from voice_contracts.tools import args_hash

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
SECRET = b"test-secret-0123456789-abcdefghijklmnop"


def repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("x")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "i"], cwd=path,
                   check=True)
    return path


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    repo(h / "Desktop" / "Portfolio")
    repo(h / "Desktop" / "My Shop")
    repo(h / "code" / "deep" / "x" / "too-deep")  # beyond 3 levels: not found
    (h / "Desktop" / "notes").mkdir()
    repo(h / "Desktop" / "Portfolio" / "vendor" / "inner")  # inside a repo: not listed
    projects.invalidate()
    return h


@pytest.fixture
def agent(tmp_path, home):
    cfg = AgentConfig.from_dict({
        "apps": {}, "projects": {}, "allowed_clients": ["testclient"], "data_dir": str(tmp_path / "data"),
        "project_scan_roots": [str(home)], "projects_root": str(tmp_path / "Projects")})
    with TestClient(create_app(cfg, SECRET, FakeLauncher(), sleep=lambda s: None, browser=FakeBrowser())) as c:
        yield c, cfg


def call(client, tool, payload, approve=False):
    body = json.dumps(payload).encode()
    path = f"/tool/{tool}"
    headers = signed_headers(SECRET, "POST", path, body)
    if approve:
        headers["X-Approved-Args-Hash"] = args_hash(tool, payload)
    return client.post(path, content=body, headers=headers).json()


def test_scan_finds_repos_with_unique_slugs(agent, home):
    client, _ = agent
    found = call(client, "find_projects", {})["data"]["found"]
    assert {f["name"]: f["label"] for f in found} == {"my-shop": "My Shop", "portfolio": "Portfolio"}


def test_register_needs_approval_and_a_scanned_repo(agent, home, tmp_path):
    client, cfg = agent
    path = str((home / "Desktop" / "Portfolio").resolve())
    assert "approval" in call(client, "register_project", {"name": "portfolio", "path": path})["error"]
    outside = repo(tmp_path / "elsewhere" / "secret")
    r = call(client, "register_project", {"name": "secret", "path": str(outside)}, approve=True)
    assert not r["ok"] and "usual folders" in r["error"]
    notes = call(client, "register_project", {"name": "notes", "path": str(home / "Desktop" / "notes")}, approve=True)
    assert not notes["ok"]
    r = call(client, "register_project", {"name": "portfolio", "path": path}, approve=True)
    assert r["ok"] and r["verified"] and cfg.projects["portfolio"].base_branch == "main"
    assert call(client, "register_project", {"name": "p2", "path": path}, approve=True)["error"].endswith(
        "already registered")
    # the coding tools now accept it, and a restart keeps it
    assert call(client, "git_status", {"project": "portfolio"})["data"]["branch"] == "main"
    fresh = AgentConfig.from_dict({"data_dir": cfg.data_dir})
    projects.load_registered(fresh)
    assert fresh.projects["portfolio"].path == path


def test_create_project(agent, tmp_path):
    client, cfg = agent
    payload = {"name": "todo-app", "description": "a todo app"}
    assert "approval" in call(client, "create_project", payload)["error"]
    r = call(client, "create_project", payload, approve=True)
    p = tmp_path / "Projects" / "todo-app"
    assert r["ok"] and (p / ".git").is_dir() and "a todo app" in (p / "README.md").read_text()
    assert "todo-app" in cfg.projects
    assert "already exists" in call(client, "create_project", payload, approve=True)["error"]


def test_status_reports_projects_without_blocking(agent):
    client, _ = agent
    from agent.tools.status import status_data
    data = status_data(client.app.state.ctx)
    assert data["projects"] == [] and isinstance(data["found_projects"], list)


def test_nested_roots_do_not_hide_deeper_repos(tmp_path):
    """Live bug: home was walked first, so ~/OneDrive/Desktop/Whale/voice-pc-control was never reached."""
    home = tmp_path / "home"
    desk = home / "OneDrive" / "Desktop"
    repo(desk / "Whale" / "voice-pc-control")
    projects.invalidate()
    cfg = AgentConfig.from_dict({"data_dir": str(tmp_path / "d"), "projects_root": str(tmp_path / "P"),
                                 "project_scan_roots": [str(home), str(desk)]})
    assert [f["label"] for f in projects.scan(cfg)] == ["voice-pc-control"]
