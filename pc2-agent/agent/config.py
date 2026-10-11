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
class AgentConfig:
    apps: dict[str, AppEntry] = field(default_factory=dict)
    browser_argv: list[str] = field(default_factory=list)  # URL is appended as one argv element
    browser_process: str = "chrome.exe"
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_clients: list[str] = field(default_factory=list)  # PC1 / VPN IPs; empty = any (dev only)
    rate_limit_per_min: int = 30
    verify_timeout_s: float = 8.0
    tool_timeout_s: float = 15.0
    data_dir: str = "agent-data"
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
        d["browser_argv"] = [os.path.expandvars(a) for a in d.get("browser_argv", [])]
        if "data_dir" in d:
            d["data_dir"] = os.path.expandvars(d["data_dir"])
        return cls(apps=apps, **d)

    @classmethod
    def load(cls, path: str | Path) -> AgentConfig:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
