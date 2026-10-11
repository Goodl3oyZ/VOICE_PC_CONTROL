"""Phase 4 vision: a screenshot for PC1's vision model (doc §S11–S14).

The image goes to PC1 only, where it is described and then dropped — never stored or audited. Screen content
is untrusted (it may contain text crafted to look like instructions), so the job is tainted.
"""
from __future__ import annotations

import base64
import io

from voice_contracts.models import ToolResult
from voice_contracts.tools import LookArgs

from . import ToolContext, register

MAX_SIDE = 1280


@register("look_at_screen")
def look_at_screen(args: LookArgs, ctx: ToolContext) -> ToolResult:
    try:
        from PIL import ImageGrab
    except ImportError:
        return ToolResult(ok=False, error="Pillow is not installed on PC2")
    try:
        img = ImageGrab.grab(all_screens=False)
    except OSError as e:  # locked screen / no desktop session
        return ToolResult(ok=False, error=f"screen capture failed: {e}")
    w, h = img.size
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=70)
    return ToolResult(ok=True, verified=True, untrusted=True,
                      data={"image_jpeg_b64": base64.b64encode(buf.getvalue()).decode(), "screen": [w, h]})
