"""get_status / stop_all (risk 0, always allowed)."""
from __future__ import annotations

from voice_contracts.models import ToolResult
from voice_contracts.tools import NoArgs

from . import ToolContext, register


def status_data(ctx: ToolContext) -> dict[str, object]:
    running = [name for name, e in ctx.cfg.apps.items() if ctx.launcher.is_running(e.process)]
    return {"running": running, "kill_switch": ctx.kill.on, "version": "0.1.0"}


@register("get_status")
def get_status(args: NoArgs, ctx: ToolContext) -> ToolResult:
    return ToolResult(ok=True, verified=True, data=status_data(ctx))


@register("stop_all")
def stop_all(args: NoArgs, ctx: ToolContext) -> ToolResult:
    ctx.cancel.set()  # running tools see this in wait_until and abort
    return ToolResult(ok=True, verified=True, data={"stopped": True})
