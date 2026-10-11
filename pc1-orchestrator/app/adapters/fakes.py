"""Fakes for every port (doc §15.4): test the core without GPU, Ollama or PC2."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from voice_contracts.models import ToolCall, ToolResult

from ..ports import PC2Unavailable, PlanContext, PlanResult, Transcript


class FakeSTT:
    """Returns a fixed transcript, or looks one up by the audio bytes."""

    def __init__(self, text: str = "", confidence: float = 0.95,
                 by_audio: dict[bytes, tuple[str, float]] | None = None):
        self.text, self.confidence, self.by_audio = text, confidence, by_audio or {}

    async def transcribe(self, audio: bytes, mime: str) -> Transcript:
        text, conf = self.by_audio.get(audio, (self.text, self.confidence))
        return Transcript(text=text, confidence=conf)


class ScriptedLLM:
    """Returns PlanResults from a list (in order) or from a function(text, ctx)."""

    def __init__(self, script: list[PlanResult] | Callable[[str, PlanContext], PlanResult] | None = None,
                 delay: float = 0.0):
        self.script = script if script is not None else []
        self.calls: list[tuple[str, PlanContext]] = []
        self.delay = delay

    vision_answer = "A code editor is open."
    images_seen = 0

    async def describe_image(self, image_b64: str, question: str) -> str:
        self.images_seen += 1
        return self.vision_answer

    async def plan(self, text: str, ctx: PlanContext) -> PlanResult:
        self.calls.append((text, ctx))
        if self.delay:
            await asyncio.sleep(self.delay)
        if callable(self.script):
            return self.script(text, ctx)
        if not self.script:
            return PlanResult(kind="final", message="ไม่มีเครื่องมือที่ทำคำสั่งนี้ได้")
        return self.script.pop(0)

    @staticmethod
    def tool(name: str, **arguments: Any) -> PlanResult:
        return PlanResult(kind="tool_call", call=ToolCall(tool=name, arguments=arguments))


class FakePC2:
    """Simulates the Windows agent: records calls, models running apps, idempotency."""

    def __init__(self, running: set[str] | None = None):
        self.calls: list[dict[str, Any]] = []
        self.running = set(running or ())
        self.offline = False
        self.fail_verify = False
        self.delay = 0.0
        self.stopped = 0
        self.kill_switch = False
        self.handlers: dict[str, Callable[[dict[str, Any]], ToolResult]] = {}  # extra tools in tests
        self._idem: dict[str, ToolResult] = {}

    async def call(self, tool: str, arguments: dict[str, Any], idempotency_key: str,
                   approved_hash: str | None = None) -> ToolResult:
        if self.offline:
            raise PC2Unavailable("connection refused")
        if idempotency_key in self._idem:
            return self._idem[idempotency_key]
        self.calls.append({"tool": tool, "arguments": arguments, "key": idempotency_key,
                           "approved_hash": approved_hash})
        if self.delay:
            await asyncio.sleep(self.delay)
        if tool == "open_app":
            app = arguments["app"]
            already = app in self.running
            self.running.add(app)
            res = ToolResult(ok=True, verified=not self.fail_verify,
                             data={"app": app, "already_running": already})
        elif tool == "open_url":
            res = ToolResult(ok=True, verified=not self.fail_verify, data={"url": arguments["url"]})
        elif tool == "get_status":
            res = ToolResult(ok=True, verified=True, data={"running": sorted(self.running),
                                                            "kill_switch": self.kill_switch})
        elif tool == "stop_all":
            res = await self.stop_all()
        elif tool in self.handlers:
            res = self.handlers[tool](arguments)
        else:
            res = ToolResult(ok=False, error=f"unknown tool {tool}")
        self._idem[idempotency_key] = res
        return res

    async def stop_all(self) -> ToolResult:
        if self.offline:
            raise PC2Unavailable("connection refused")
        self.stopped += 1
        return ToolResult(ok=True, verified=True, data={"stopped": True})

    async def status(self) -> ToolResult:
        if self.offline:
            raise PC2Unavailable("connection refused")
        return ToolResult(ok=True, verified=True, data={"running": sorted(self.running),
                                                         "kill_switch": self.kill_switch})


class ListNotifier:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)
