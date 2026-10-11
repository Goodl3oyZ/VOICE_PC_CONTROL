"""Job entity + state machine (doc §14.3, figure 14-2).

Every command is a Job with an explicit state. Only the transitions listed in
TRANSITIONS are legal, so there are no "floating" jobs with unknown status.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    CREATED = "created"
    TRANSCRIBING = "transcribing"
    PLANNING = "planning"
    CLARIFYING = "clarifying"
    ROUTING = "routing"
    AWAITING_CONFIRM = "awaiting_confirm"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


S = JobState
TERMINAL = frozenset({S.DONE, S.FAILED, S.CANCELLED})

TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    S.CREATED: frozenset({S.TRANSCRIBING, S.PLANNING}),
    S.TRANSCRIBING: frozenset({S.PLANNING, S.CLARIFYING}),
    # planning -> done only after a verified step, when the LLM decides it is finished (§14.2 step 10).
    S.PLANNING: frozenset({S.ROUTING, S.CLARIFYING, S.DONE}),
    S.CLARIFYING: frozenset({S.PLANNING}),
    S.ROUTING: frozenset({S.DISPATCHING, S.AWAITING_CONFIRM}),
    S.AWAITING_CONFIRM: frozenset({S.DISPATCHING}),
    S.DISPATCHING: frozenset({S.RUNNING}),
    S.RUNNING: frozenset({S.VERIFYING}),
    S.VERIFYING: frozenset({S.DONE, S.PLANNING}),
}
# From any non-terminal state: error/timeout/deny -> failed, Stop -> cancelled.
for _s in list(JobState):
    if _s not in TERMINAL:
        TRANSITIONS[_s] = TRANSITIONS.get(_s, frozenset()) | {S.FAILED, S.CANCELLED}


class InvalidTransition(Exception):
    pass


def new_job_id(now: float | None = None) -> str:
    t = time.localtime(now if now is not None else time.time())
    return f"j_{time.strftime('%Y%m%d_%H%M%S', t)}_{secrets.token_hex(3)}"


@dataclass
class Job:
    id: str
    device: str
    source: str  # "text" | "audio"
    state: JobState = S.CREATED
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    text: str = ""  # transcript or typed text
    normalized: str = ""
    stt_confidence: float | None = None
    question: str | None = None  # when clarifying
    clarify_kind: str | None = None  # "stt_confirm" | "llm"
    pending: dict[str, Any] | None = None  # awaiting_confirm: tool, arguments, args_hash, risk, expires_at
    steps: list[dict[str, Any]] = field(default_factory=list)  # tool calls + results
    summary: str = ""
    error: str | None = None
    outcome: str | None = None  # done_verified | denied | failed | cancelled
    tainted: bool = False
    planner: str | None = None  # "shortcut" | "llm"
    timings_ms: dict[str, int] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)  # clarification Q/A

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL

    def transition(self, new: JobState, now: float | None = None) -> JobState:
        if self.terminal:
            raise InvalidTransition(f"{self.id}: {self.state} is terminal")
        if new not in TRANSITIONS[self.state]:
            raise InvalidTransition(f"{self.id}: {self.state} -> {new} not allowed")
        old, self.state = self.state, new
        self.updated_at = now if now is not None else time.time()
        return old

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = str(self.state)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Job:
        d = dict(d)
        d["state"] = JobState(d["state"])
        return cls(**d)

    def public(self) -> dict[str, Any]:
        """What the phone sees (no internal history noise)."""
        d = self.to_dict()
        d.pop("history", None)
        return d
