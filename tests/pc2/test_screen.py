"""PC2 screenshot tool (Phase 4 vision): small JPEG, marked untrusted."""
from __future__ import annotations

import base64
import sys

import pytest

pytest.importorskip("PIL")


@pytest.mark.skipif(sys.platform != "win32", reason="needs a Windows desktop")
def test_look_at_screen_returns_small_jpeg():
    from agent.tools.screen import look_at_screen
    from voice_contracts.tools import LookArgs

    r = look_at_screen(LookArgs(), None)  # type: ignore[arg-type]
    assert r.ok and r.untrusted
    jpeg = base64.b64decode(r.data["image_jpeg_b64"])
    assert jpeg[:2] == b"\xff\xd8" and len(jpeg) < 600_000
