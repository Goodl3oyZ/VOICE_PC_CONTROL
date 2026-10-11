"""System Knowledge (doc ch.6): apps, sites, aliases, limits — loaded from JSON."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Knowledge:
    apps: dict[str, dict[str, Any]] = field(default_factory=dict)  # canonical -> {"display": ...}
    sites: dict[str, str] = field(default_factory=dict)  # canonical -> https URL
    allowed_hosts: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)  # spoken form -> canonical
    projects: dict[str, dict[str, Any]] = field(default_factory=dict)  # Phase 3: name -> {"display": ...}
    limits: list[str] = field(default_factory=list)
    memory: list[str] = field(default_factory=list)  # user-approved preferences

    @classmethod
    def load(cls, path: str | Path) -> Knowledge:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if not k.startswith("_")})

    def display(self, app: str, language: str = "th") -> str:
        entry = self.apps.get(app, {})
        name = entry.get(f"display_{language}") or entry.get("display", app)
        if language == "en" and any("\u0e00" <= ch <= "\u0e7f" for ch in name):
            return app.title()  # no English display name configured
        return name

    def prompt_summary(self) -> str:
        apps = ", ".join(f"{k} ({self.display(k)})" for k in self.apps)
        sites = ", ".join(f"{k}={v}" for k, v in self.sites.items())
        lines = [f"Apps (allowlist): {apps}", f"Sites: {sites}"]
        if self.projects:
            lines.append("Code projects: " + ", ".join(self.projects))
        if self.memory:
            lines.append("User preferences: " + "; ".join(self.memory))
        if self.limits:
            lines.append("Limits: " + "; ".join(self.limits))
        return "\n".join(lines)
