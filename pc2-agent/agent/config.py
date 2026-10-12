"""Agent configuration (allowlists live on PC2 too — defense in depth, §19.5)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AppEntry:
    process: str  # e.g. "chrome.exe" — used to verify the app really started
    argv: list[str] | None = None  # launched without a shell
    uri: str | None = None  # e.g. "spotify:" via the registered handler


@dataclass
class ProjectEntry:
    path: str
    test_cmd: list[str] = field(default_factory=list)  # argv, no shell; e.g. ["npm", "test"]
    ide: str = "cursor"  # app name from `apps` used by open_project
    base_branch: str = "main"


@dataclass
class AgentConfig:
    apps: dict[str, AppEntry] = field(default_factory=dict)
    projects: dict[str, ProjectEntry] = field(default_factory=dict)  # Phase 3 coding
    projects_root: str = "%USERPROFILE%/Projects"  # where "Start a new project" creates folders
    project_scan_roots: list[str] = field(default_factory=list)  # where to look for git repos; [] = home folders
    tests_timeout_s: float = 120.0
    browser_argv: list[str] = field(default_factory=list)  # URL is appended as one argv element
    browser_process: str = "chrome.exe"
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_clients: list[str] = field(default_factory=list)  # PC1 / VPN IPs; empty = any (dev only)
    rate_limit_per_min: int = 30
    verify_timeout_s: float = 8.0
    tool_timeout_s: float = 15.0
    killswitch_hotkey: str = "ctrl+alt+shift+k"  # local kill switch (US-607); "" disables
    data_dir: str = "agent-data"
    # Phase 2 agent browser: visible window, dedicated profile (default <data_dir>/chrome-profile)
    browser_headless: bool = False
    browser_profile_dir: str | None = None
    # Redesign step 2: "extension" drives the user's own Chrome through the Voice PC extension (bridge on
    # 127.0.0.1:extension_port); "playwright" keeps the old separate automated browser.
    browser_mode: str = "extension"
    extension_port: int = 8766
    # Outbound mode: dial PC1 (e.g. wss://pc.example.com/agent/ws) instead of listening for PC1.
    pc1_ws_url: str | None = None
    bind_host: str = "127.0.0.1"
    port: int = 8765
    tls_certfile: str | None = None
    tls_keyfile: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentConfig:
        d = {k: v for k, v in d.items() if not k.startswith("_")}
        apps = {}
        for name, e in d.pop("apps", {}).items():
            argv = [os.path.expandvars(a) for a in e["argv"]] if e.get("argv") else None
            apps[name] = AppEntry(process=e["process"], argv=argv, uri=e.get("uri"))
        projects = {}
        for name, e in d.pop("projects", {}).items():
            projects[name] = ProjectEntry(path=os.path.expandvars(e["path"]),
                                          test_cmd=[os.path.expandvars(a) for a in e.get("test_cmd", [])],
                                          ide=e.get("ide", "cursor"), base_branch=e.get("base_branch", "main"))
        d["projects"] = projects
        d["browser_argv"] = [os.path.expandvars(a) for a in d.get("browser_argv", [])]
        if "data_dir" in d:
            d["data_dir"] = os.path.expandvars(d["data_dir"])
        return cls(apps=apps, **d)

    @classmethod
    def load(cls, path: str | Path) -> AgentConfig:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
