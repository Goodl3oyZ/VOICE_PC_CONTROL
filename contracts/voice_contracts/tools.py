"""Tool catalogue (doc ch.7) — argument schemas + risk levels.

Risk levels (§10.2): 0 read-only · 1 open app · 2 edit within scope ·
3 external effect / hard to undo (confirm on phone) · 4 forbidden by default.

Per-machine allowlists (which apps, which hosts) are NOT hard-coded here; PC1
injects them as an enum into the LLM schema and both PC1 and PC2 enforce them.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote_plus, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

NAME_PATTERN = r"^[a-z0-9_\-]{1,32}$"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OpenAppArgs(_Args):
    app: str = Field(pattern=NAME_PATTERN, description="Canonical app name from the allowlist")


class OpenUrlArgs(_Args):
    url: str = Field(max_length=2048, description="https:// URL on an allowed host")

    @field_validator("url")
    @classmethod
    def _https_only(cls, v: str) -> str:
        parts = urlsplit(v)
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("only https URLs are allowed")
        if parts.username or parts.password:
            raise ValueError("credentials in URL are not allowed")
        if any(c.isspace() for c in v):
            raise ValueError("whitespace in URL")
        return v


class NoArgs(_Args):
    pass


SEARCH_SITES = {
    "google": "https://www.google.com/search?q=",
    "youtube": "https://www.youtube.com/results?search_query=",
}


class SearchWebArgs(_Args):
    query: str = Field(min_length=1, max_length=200, description="What to search for (Thai or English)")
    site: Literal["google", "youtube"] = Field("google", description="google = web search, youtube = videos/music")

    @field_validator("query")
    @classmethod
    def _printable(cls, v: str) -> str:
        if any(ord(c) < 32 for c in v):
            raise ValueError("control characters not allowed")
        return v


def search_url(site: str, query: str) -> str:
    return SEARCH_SITES[site] + quote_plus(query)


MEDIA_ACTIONS = ("play_pause", "next", "previous", "volume_up", "volume_down", "mute")


class MediaControlArgs(_Args):
    action: Literal["play_pause", "next", "previous", "volume_up", "volume_down", "mute"] = Field(
        description="play_pause toggles play/pause; next/previous track; volume_up/down; mute toggles")
    steps: int = Field(1, ge=1, le=25, description="Repeat count for volume (1 step = 2% volume)")


# ---- Phase 2: agent browser (Playwright, dedicated Chrome profile on PC2) ----
class _QueryArgs(_Args):
    query: str = Field(min_length=1, max_length=200)

    @field_validator("query")
    @classmethod
    def _printable(cls, v: str) -> str:
        if any(ord(c) < 32 for c in v):
            raise ValueError("control characters not allowed")
        return v


class WebSearchArgs(_QueryArgs):
    max_results: int = Field(5, ge=1, le=8, description="How many results to return")
    site: Literal["web", "youtube"] = Field("web", description="web = web pages, youtube = videos/music")


class OpenResultArgs(_Args):
    index: int = Field(ge=1, le=8, description="1-based number of a result from the last web_search")


class YoutubePlayArgs(_QueryArgs):
    pass


class BrowserTabsArgs(_Args):
    action: Literal["list", "next", "previous", "close"] = Field(
        description="list open tabs, switch to next/previous tab, or close the current tab")


# ---- Phase 3: AI coding agent (projects registered on PC2; edits only on an ai/* git branch) ----
_REL_PATH_CHARS = re.compile(r"^[\w .\-\\/]{0,300}$")


def safe_rel_path(v: str) -> str:
    """Relative path inside a project: no drive, no leading slash, no "..", no odd characters.
    PC2 additionally resolves the real path and checks it stays inside the project (symlinks, TC-S04)."""
    if not _REL_PATH_CHARS.match(v) or v.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", v):
        raise ValueError("path must be relative to the project")
    if any(part == ".." for part in re.split(r"[\\/]", v)):
        raise ValueError("'..' is not allowed")
    return v


class ProjectArgs(_Args):
    project: str = Field(pattern=NAME_PATTERN, description="Registered project name")


class ListFilesArgs(ProjectArgs):
    subdir: str = Field("", max_length=300, description="Folder inside the project ('' = root)")
    _v = field_validator("subdir")(classmethod(lambda cls, v: safe_rel_path(v)))


class ReadFileArgs(ProjectArgs):
    path: str = Field(min_length=1, max_length=300, description="File path inside the project")
    _v = field_validator("path")(classmethod(lambda cls, v: safe_rel_path(v)))


class SearchCodeArgs(ProjectArgs):
    query: str = Field(min_length=2, max_length=100, description="Text to find in the project files")


class EditFileArgs(ProjectArgs):
    # Code must be kept byte-exact: never strip whitespace (indentation, trailing newlines).
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    path: str = Field(min_length=1, max_length=300)
    _v = field_validator("path")(classmethod(lambda cls, v: safe_rel_path(v)))
    old_text: str = Field("", max_length=4000, description="Exact text to replace ('' = create a new file)")
    new_text: str = Field(max_length=8000, description="Replacement text")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    risk: int
    args: type[_Args]
    description: str
    phase: int
    enabled: bool = True  # feature flag (§19.6)


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec("open_app", 1, OpenAppArgs, "Open an allowed app on PC2 (เปิดโปรแกรมที่อยู่ใน allowlist)", 1),
        ToolSpec("open_url", 1, OpenUrlArgs, "Open an allowed https website in the PC2 browser (เปิดเว็บที่อนุญาต)", 1),
        ToolSpec("get_status", 0, NoArgs, "Show PC2 status and which apps are running (ดูสถานะ PC2)", 1),
        ToolSpec("stop_all", 0, NoArgs, "Stop everything that is running right now (หยุดงานทั้งหมด)", 1),
        # Disabled: it opened a NEW tab in the user's Chrome on every search. web_search (agent browser)
        # reuses the existing search/YouTube tab instead. Kept for VPC_LANGUAGE=th installs that rely on it.
        ToolSpec("search_web", 1, SearchWebArgs,
                 "Search Google, or find videos/music on YouTube, and open the results in Chrome on PC2 (ค้นหา)", 1,
                 enabled=False),
        ToolSpec("media_control", 1, MediaControlArgs,
                 "Control what is playing (Spotify, YouTube): play/pause, next/previous track, "
                 "volume up/down, mute. 1 volume step = 2% (ควบคุมเพลงและเสียง)", 1),
        # Phase 2 — results from the web are UNTRUSTED data (taint): risk >= 2 tools then need confirmation.
        ToolSpec("web_search", 0, WebSearchArgs,
                 "Search the web (or YouTube with site=youtube) in the agent browser on PC2, "
                 "return the top results. "
                 "Reuses the existing search tab", 2),
        ToolSpec("open_result", 1, OpenResultArgs,
                 "Open result number N from the last web_search in the agent browser", 2),
        ToolSpec("youtube_play", 1, YoutubePlayArgs,
                 "Find a video or song on YouTube and start playing the first result in the agent browser", 2),
        ToolSpec("browser_tabs", 1, BrowserTabsArgs,
                 "List, switch (next/previous) or close tabs in the agent browser", 2),
        # Phase 3 — coding. Reads are risk 0; edits/tests change files -> risk 2 (git branch + checkpoint).
        ToolSpec("open_project", 1, ProjectArgs, "Open a registered project in the IDE (Cursor) on PC2", 3),
        ToolSpec("list_files", 0, ListFilesArgs, "List files and folders of a registered project", 3),
        ToolSpec("read_file", 0, ReadFileArgs, "Read a text file of a registered project", 3),
        ToolSpec("search_code", 0, SearchCodeArgs, "Find text in a project's files (file, line, text)", 3),
        ToolSpec("git_status", 0, ProjectArgs, "Show the project's git branch and changed files", 3),
        ToolSpec("edit_file", 2, EditFileArgs,
                 "Replace exact text in a project file (or create a file). Always happens on an ai/* git "
                 "branch, never on main", 3),
        ToolSpec("run_tests", 2, ProjectArgs, "Run the project's configured test command and report the result", 3),
        ToolSpec("git_diff", 0, ProjectArgs, "Show what the AI changed compared with the base branch", 3),
        ToolSpec("revert_changes", 2, ProjectArgs,
                 "Undo all AI changes: back to the base branch, delete the ai/* branch", 3),
    ]
}


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def host_allowed(url: str, allowed_hosts: list[str] | set[str]) -> bool:
    host = host_of(url)
    return any(host == h or host.endswith("." + h) for h in allowed_hosts)


def args_hash(tool: str, arguments: dict[str, Any]) -> str:
    """Stable hash binding an approval to the exact tool + args (anti-TOCTOU, TC-S16)."""
    canonical = json.dumps({"tool": tool, "arguments": arguments}, sort_keys=True,
                           ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def llm_tool_schemas(app_enum: list[str], project_enum: list[str] | None = None) -> list[dict[str, Any]]:
    """OpenAI/Ollama-style function definitions with the app allowlist as an enum (§7.1)."""
    out = []
    for spec in TOOLS.values():
        if not spec.enabled:
            continue
        params = spec.args.model_json_schema()
        params.pop("title", None)
        if spec.name == "open_app":
            params["properties"]["app"]["enum"] = app_enum
            params["properties"]["app"].pop("pattern", None)
        if "project" in params.get("properties", {}):
            if not project_enum:
                continue  # no projects registered: don't offer coding tools at all
            params["properties"]["project"]["enum"] = project_enum
            params["properties"]["project"].pop("pattern", None)
        out.append({"type": "function",
                    "function": {"name": spec.name, "description": spec.description,
                                 "parameters": params}})
    return out
