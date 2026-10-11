"""Tool plugins: one module per tool, registered by name (Open/Closed, §15.4)."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from voice_contracts.models import ToolResult

from ..config import AgentConfig
from ..launcher import Launcher
from ..policy import KillSwitch


@dataclass
class ToolContext:
    cfg: AgentConfig
    launcher: Launcher
    kill: KillSwitch
    cancel: threading.Event = field(default_factory=threading.Event)
    browser: Any = None  # agent.browser.Browser (Phase 2)
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def wait_until(self, cond: Callable[[], bool], timeout: float, interval: float = 0.25) -> bool:
        """Post-action verification loop; aborts early on Stop."""
        deadline = self.clock() + timeout
        while True:
            if cond():
                return True
            if self.cancel.is_set() or self.clock() >= deadline:
                return False
            self.sleep(interval)


ToolFn = Callable[[BaseModel, ToolContext], ToolResult]
REGISTRY: dict[str, ToolFn] = {}


def register(name: str) -> Callable[[ToolFn], ToolFn]:
    def deco(fn: ToolFn) -> ToolFn:
        REGISTRY[name] = fn
        return fn
    return deco


from . import apps, media, status, web  # noqa: E402,F401  (registers tools)
