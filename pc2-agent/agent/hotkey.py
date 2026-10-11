"""Local kill switch hotkey on PC2 (US-607): works with no network, no phone, no PC1.

Press once (default Ctrl+Alt+Shift+K): stop everything running and refuse every tool call (the flag file
survives restarts). Press again: release. A beep confirms each change and it is written to the audit log.
"""
from __future__ import annotations

import logging
import sys
import threading
from typing import Any

log = logging.getLogger("pc2.hotkey")

MODS = {"ctrl": 0x0002, "control": 0x0002, "alt": 0x0001, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
NAMED_KEYS = {"pause": 0x13, "end": 0x23, "home": 0x24, "insert": 0x2D, "delete": 0x2E, "esc": 0x1B,
              "escape": 0x1B, "space": 0x20}


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+alt+shift+k' -> (modifiers, virtual-key code). At least one modifier is required."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError("hotkey needs a modifier and a key, e.g. ctrl+alt+shift+k")
    mods = 0
    for p in parts[:-1]:
        if p not in MODS:
            raise ValueError(f"unknown modifier: {p}")
        mods |= MODS[p]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key in NAMED_KEYS:
        vk = NAMED_KEYS[key]
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"unknown key: {key}")
    return mods, vk


def toggle_kill(app: Any) -> bool:
    """Flip the kill switch as the local user; when engaging, also stop everything. Returns the new state."""
    from .tools import REGISTRY

    kill, ctx, audit = app.state.kill, app.state.ctx, app.state.audit
    on = not kill.on
    kill.set(on)
    if on:
        ctx.cancel.set()
        try:
            REGISTRY["stop_all"](None, ctx)
        except Exception:  # noqa: BLE001 - the switch itself must never fail
            log.exception("stop_all during kill switch failed")
    try:
        audit.append("killswitch", {"on": on, "via": "hotkey"})
    except Exception:  # noqa: BLE001
        log.exception("audit write failed")
    log.warning("KILL SWITCH %s via hotkey", "ENGAGED" if on else "released")
    return on


def _beep(on: bool) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBeep(0x10 if on else 0x40)  # type: ignore[attr-defined]


def start_hotkey_thread(app: Any, spec: str) -> threading.Thread | None:
    """Register a global hotkey on a background thread (Windows only)."""
    if sys.platform != "win32" or not spec:
        return None
    mods, vk = parse_hotkey(spec)

    def loop() -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        if not user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk):
            log.error("could not register kill switch hotkey %s (in use by another program?)", spec)
            return
        log.info("kill switch hotkey: %s", spec)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                _beep(toggle_kill(app))

    t = threading.Thread(target=loop, name="killswitch-hotkey", daemon=True)
    t.start()
    return t
