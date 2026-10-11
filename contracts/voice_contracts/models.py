from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """What the planner (rules or LLM) wants to run. Never trusted as-is."""

    tool: str = Field(max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Shown to the user only; never used for authorisation decisions (§14.4).
    rationale: str = Field(default="", max_length=500)


class ToolResult(BaseModel):
    ok: bool
    verified: bool = False  # post-action check passed (FR-05)
    data: dict[str, Any] = Field(default_factory=dict)
    untrusted: bool = False  # content came from outside -> taint (FR-09)
    error: str | None = None
    elapsed_ms: int = 0


DecisionKind = Literal["allow", "confirm", "deny"]


class Decision(BaseModel):
    decision: DecisionKind
    risk: int = 0
    reason: str = ""
    args_hash: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)  # validated/normalised args
