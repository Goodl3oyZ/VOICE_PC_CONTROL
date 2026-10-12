"""Ports (doc §15.4): the core only knows these interfaces, never FastAPI/Ollama/SQLite.

Each port has a real adapter and a fake (app/adapters/fakes.py) for tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from voice_contracts.models import ToolCall, ToolResult


@dataclass
class Transcript:
    text: str
    confidence: float
    lang: str = "th"


@dataclass
class PlanContext:
    knowledge_summary: str
    tools: list[dict[str, Any]]  # LLM function schemas (with allowlist enums)
    history: list[dict[str, str]] = field(default_factory=list)  # clarification Q/A
    observations: list[dict[str, Any]] = field(default_factory=list)  # previous step results


@dataclass
class PlanResult:
    kind: Literal["tool_call", "clarify", "final", "invalid"]
    call: ToolCall | None = None
    message: str = ""


class STTPort(Protocol):
    async def transcribe(self, audio: bytes, mime: str, language: str | None = None) -> Transcript: ...


class LLMPort(Protocol):
    async def plan(self, text: str, ctx: PlanContext) -> PlanResult: ...


class PC2Unavailable(Exception):
    """PC2 could not be reached (network/offline). Feeds the circuit breaker."""


class ToolPort(Protocol):
    async def call(self, tool: str, arguments: dict[str, Any], idempotency_key: str,
                   approved_hash: str | None = None) -> ToolResult: ...

    async def stop_all(self) -> ToolResult: ...

    async def status(self) -> ToolResult: ...


class AuditWriteError(Exception):
    pass


class StorePort(Protocol):
    def save_job(self, job_dict: dict[str, Any]) -> None: ...
    def get_job(self, job_id: str) -> dict[str, Any] | None: ...
    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]: ...
    def list_unfinished_jobs(self) -> list[dict[str, Any]]: ...
    def append_audit(self, kind: str, job_id: str | None, data: dict[str, Any]) -> None: ...
    def verify_audit(self) -> bool: ...
    def add_event(self, job_id: str, stage: str, status: str, duration_ms: int,
                  **extra: Any) -> None: ...


class NotifyPort(Protocol):
    async def publish(self, event: dict[str, Any]) -> None: ...
