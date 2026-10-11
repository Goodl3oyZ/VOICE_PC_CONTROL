"""media_control: Windows media/volume keys (risk 1).

Media keys are handled by whatever is playing — Spotify, YouTube in Chrome, Windows Media Player — so one
tool covers them all without app-specific APIs. Windows gives no reliable read-back of "what is playing",
so the result reports that the keys were sent (verified = keys delivered), not that a song changed.
"""
from __future__ import annotations

import sys
from collections.abc import Callable

from voice_contracts.models import ToolResult
from voice_contracts.tools import MediaControlArgs

from . import ToolContext, register

VK = {  # virtual-key codes
    "play_pause": 0xB3, "next": 0xB0, "previous": 0xB1,
    "mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
}
KEYEVENTF_KEYUP = 0x0002


def _send_key_windows(vk: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def key_sender() -> Callable[[int], None] | None:
    return _send_key_windows if sys.platform == "win32" else None


@register("media_control")
def media_control(args: MediaControlArgs, ctx: ToolContext) -> ToolResult:
    send = getattr(ctx.launcher, "send_key", None) or key_sender()
    if send is None:
        return ToolResult(ok=False, error="media keys are only supported on Windows")
    repeat = args.steps if args.action in ("volume_up", "volume_down") else 1
    for _ in range(repeat):
        if ctx.cancel.is_set():
            break
        send(VK[args.action])
        ctx.sleep(0.03)
    return ToolResult(ok=True, verified=True, data={"action": args.action, "steps": repeat})
