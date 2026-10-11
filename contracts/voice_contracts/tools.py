"""Tool catalogue (doc ch.7) — argument schemas + risk levels.

Risk levels (§10.2): 0 read-only · 1 open app · 2 edit within scope ·
3 external effect / hard to undo (confirm on phone) · 4 forbidden by default.

Per-machine allowlists (which apps, which hosts) are NOT hard-coded here; PC1
injects them as an enum into the LLM schema and both PC1 and PC2 enforce them.
"""
from __future__ import annotations

import hashlib
import json
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
        ToolSpec("search_web", 1, SearchWebArgs,
                 "Search Google, or find videos/music on YouTube, and open the results in Chrome on PC2 (ค้นหา)", 1),
        ToolSpec("media_control", 1, MediaControlArgs,
                 "Control what is playing (Spotify, YouTube): play/pause, next/previous track, "
                 "volume up/down, mute. 1 volume step = 2% (ควบคุมเพลงและเสียง)", 1),
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


def llm_tool_schemas(app_enum: list[str]) -> list[dict[str, Any]]:
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
        out.append({"type": "function",
                    "function": {"name": spec.name, "description": spec.description,
                                 "parameters": params}})
    return out
