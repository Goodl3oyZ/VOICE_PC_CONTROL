"""Tool Router policy — deny by default (doc §10.2, §15.4, §20.5).

The LLM is an untrusted component: whatever it proposes is validated here by
deterministic rules before anything reaches PC2.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import ValidationError

from voice_contracts.models import Decision, ToolCall
from voice_contracts.tools import TOOLS, args_hash, host_allowed

from .knowledge import Knowledge

# Tools that must keep working even when limits/kill switch are on.
ALWAYS_ALLOWED = frozenset({"stop_all", "get_status"})


class RateLimiter:
    """Sliding window: at most `limit` actions per `window` seconds (§10.3, LLM10)."""

    def __init__(self, limit: int = 20, window: float = 60.0, clock: Callable[[], float] = time.time):
        self.limit, self.window, self._clock = limit, window, clock
        self._hits: deque[float] = deque()

    def hit(self) -> bool:
        now = self._clock()
        while self._hits and now - self._hits[0] > self.window:
            self._hits.popleft()
        if len(self._hits) >= self.limit:
            return False
        self._hits.append(now)
        return True


@dataclass
class PolicyContext:
    knowledge: Knowledge
    rate: RateLimiter = field(default_factory=RateLimiter)
    kill_switch: bool = False
    tainted: bool = False


def _deny(reason: str, risk: int = 0) -> Decision:
    return Decision(decision="deny", risk=risk, reason=reason)


def decide(call: ToolCall, ctx: PolicyContext) -> Decision:
    spec = TOOLS.get(call.tool)
    if spec is None or not spec.enabled:
        return _deny("unknown tool")
    try:
        args = spec.args.model_validate(call.arguments).model_dump()
    except ValidationError as e:
        return _deny(f"bad args: {e.errors()[0]['type']}", spec.risk)

    if call.tool == "open_app" and args["app"] not in ctx.knowledge.apps:
        return _deny("app not in allowlist", spec.risk)
    if call.tool == "open_url" and not host_allowed(args["url"], ctx.knowledge.allowed_hosts):
        return _deny("host not in allowlist", spec.risk)

    if call.tool not in ALWAYS_ALLOWED:
        if ctx.kill_switch:
            return _deny("kill switch on", spec.risk)
        if not ctx.rate.hit():
            return _deny("rate limit", spec.risk)

    h = args_hash(call.tool, args)
    if spec.risk >= 4:
        return _deny("forbidden by default", spec.risk)
    if ctx.tainted and spec.risk >= 2:
        return Decision(decision="confirm", risk=spec.risk, reason="tainted context",
                        args_hash=h, arguments=args)
    if spec.risk >= 3:
        return Decision(decision="confirm", risk=spec.risk, reason="high risk",
                        args_hash=h, arguments=args)
    return Decision(decision="allow", risk=spec.risk, reason="ok", args_hash=h, arguments=args)
