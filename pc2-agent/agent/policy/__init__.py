"""PC2 policy layer: re-checks everything PC1 already checked (defense in depth, §14.2 step 7)."""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from voice_contracts.tools import TOOLS, args_hash, host_allowed

from ..config import AgentConfig

ALWAYS_ALLOWED = frozenset({"stop_all", "get_status"})


class RateLimiter:
    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.time):
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
class Check:
    ok: bool
    reason: str = ""
    args: BaseModel | None = None


class KillSwitch:
    """File-backed so it survives restarts and can be flipped locally without the network (US-607)."""

    def __init__(self, path: Path):
        self.path = path

    @property
    def on(self) -> bool:
        return self.path.exists()

    def set(self, on: bool) -> None:
        if on:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("on", encoding="utf-8")
        elif self.path.exists():
            self.path.unlink()


class AgentPolicy:
    def __init__(self, cfg: AgentConfig, kill: KillSwitch, clock: Callable[[], float] = time.time):
        self.cfg, self.kill = cfg, kill
        self.rate = RateLimiter(cfg.rate_limit_per_min, 60.0, clock)

    def check(self, tool: str, raw_args: object, approved_hash: str | None = None) -> Check:
        spec = TOOLS.get(tool)
        if spec is None or not spec.enabled:
            return Check(False, "unknown tool")
        if not isinstance(raw_args, dict):
            return Check(False, "bad args: not an object")
        try:
            args = spec.args.model_validate(raw_args)
        except ValidationError as e:
            return Check(False, f"bad args: {e.errors()[0]['type']}")
        data = args.model_dump()
        if tool == "open_app" and data["app"] not in self.cfg.apps:
            return Check(False, "app not in allowlist")
        if tool == "open_url" and not host_allowed(data["url"], self.cfg.allowed_hosts):
            return Check(False, "host not in allowlist")
        if "project" in data and data["project"] not in self.cfg.projects:
            return Check(False, "project not registered")
        if tool not in ALWAYS_ALLOWED:
            if self.kill.on:
                return Check(False, "kill switch on")
            if not self.rate.hit():
                return Check(False, "rate limit")
        if spec.risk >= 4:
            return Check(False, "forbidden by default")
        if spec.risk >= 3 and approved_hash != args_hash(tool, data):
            return Check(False, "missing or mismatched approval")
        return Check(True, "ok", args)
