"""OBS through its built-in WebSocket remote control (obs-websocket v5, app flows step 5).

The password is read from OBS's own settings file on this PC (%APPDATA%/obs-studio/plugin_config/obs-websocket/
config.json), so it is never copied anywhere else. Recording and scene changes are free; starting a stream goes
public and needs the owner's approval (risk 3, separate tool); stopping a stream is always allowed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess  # nosec B404 — starts OBS from its fixed install path only
import time
import uuid
from pathlib import Path
from typing import Any

from voice_contracts.models import ToolResult
from voice_contracts.tools import NoArgs, ObsArgs

from . import ToolContext, register

OBS_EXE = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "obs-studio" / "bin" / "64bit" / "obs64.exe"


class ObsError(Exception):
    pass


def obs_config() -> dict[str, Any]:
    p = Path(os.environ.get("APPDATA", "")) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
    if not p.exists():
        raise ObsError("OBS remote control is not set up yet: open OBS once, then Tools → WebSocket Server Settings")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    if not cfg.get("server_enabled"):
        raise ObsError("OBS remote control is off: in OBS open Tools → WebSocket Server Settings and enable it")
    return cfg


def auth_string(password: str, salt: str, challenge: str) -> str:
    """obs-websocket v5: base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class ObsClient:
    def __init__(self, port: int, password: str, timeout: float = 5.0):
        from websockets.sync.client import connect

        self._cm = connect(f"ws://127.0.0.1:{port}", open_timeout=timeout, close_timeout=1)
        self.ws = self._cm.__enter__()  # the library wants a context manager; close() exits it
        self.timeout = timeout
        hello = json.loads(self.ws.recv(timeout))
        ident: dict[str, Any] = {"rpcVersion": 1}
        a = hello.get("d", {}).get("authentication")
        if a:
            ident["authentication"] = auth_string(password, a["salt"], a["challenge"])
        self.ws.send(json.dumps({"op": 1, "d": ident}))
        msg = json.loads(self.ws.recv(timeout))
        if msg.get("op") != 2:
            raise ObsError("OBS refused the connection (wrong WebSocket password?)")

    def call(self, rtype: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        rid = uuid.uuid4().hex
        self.ws.send(json.dumps({"op": 6, "d": {"requestType": rtype, "requestId": rid, "requestData": data or {}}}))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            msg = json.loads(self.ws.recv(max(0.1, deadline - time.monotonic())))
            if msg.get("op") == 7 and msg["d"].get("requestId") == rid:
                st = msg["d"]["requestStatus"]
                if not st.get("result"):
                    raise ObsError(f"OBS: {st.get('comment') or rtype + ' failed'}")
                return msg["d"].get("responseData") or {}
        raise ObsError(f"OBS did not answer {rtype}")

    def close(self) -> None:
        self._cm.__exit__(None, None, None)


def _running(ctx: ToolContext) -> bool:
    return ctx.launcher.is_running("obs64.exe")


def connect(ctx: ToolContext, start: bool = True) -> ObsClient:
    cfg = obs_config()
    if not _running(ctx):
        if not start:
            raise ObsError("OBS is not running")
        if not OBS_EXE.exists():
            raise ObsError("OBS is not installed")
        # OBS must start in its own folder (it looks for its files there); fixed path, no shell, no arguments
        # from the phone.
        subprocess.Popen([str(OBS_EXE), "--minimize-to-tray", "--disable-shutdown-check"],  # noqa: S603  # nosec B603
                         cwd=str(OBS_EXE.parent))
    last: Exception | None = None
    for _ in range(40):  # OBS takes a few seconds to open its WebSocket
        try:
            return ObsClient(int(cfg.get("server_port", 4455)), str(cfg.get("server_password", "")))
        except ObsError:
            raise
        except Exception as e:  # noqa: BLE001 — not listening yet
            last = e
            ctx.sleep(0.5)
    raise ObsError(f"could not reach OBS ({type(last).__name__})")


def status(c: ObsClient) -> dict[str, Any]:
    rec, stream = c.call("GetRecordStatus"), c.call("GetStreamStatus")
    scenes = c.call("GetSceneList")
    return {"recording": bool(rec.get("outputActive")), "record_time": rec.get("outputTimecode", ""),
            "streaming": bool(stream.get("outputActive")), "stream_time": stream.get("outputTimecode", ""),
            "scene": scenes.get("currentProgramSceneName", ""),
            "scenes": [s.get("sceneName", "") for s in reversed(scenes.get("scenes", []))][:20]}


def _wait(c: ObsClient, ctx: ToolContext, key: str, want: bool) -> dict[str, Any]:
    st: dict[str, Any] = {}
    for _ in range(20):
        st = status(c)
        if st[key] == want:
            break
        ctx.sleep(0.25)
    return st


@register("obs_control")
def obs_control(args: ObsArgs, ctx: ToolContext) -> ToolResult:
    try:
        c = connect(ctx, start=args.action not in ("stop_recording", "stop_streaming"))
    except ObsError as e:
        if args.action in ("stop_recording", "stop_streaming") and str(e) == "OBS is not running":
            return ToolResult(ok=True, verified=True, data={"recording": False, "streaming": False})
        return ToolResult(ok=False, error=str(e))
    try:
        if args.action == "status":
            st = status(c)
        elif args.action == "start_recording":
            if not status(c)["recording"]:
                c.call("StartRecord")
            st = _wait(c, ctx, "recording", True)
        elif args.action == "stop_recording":
            if status(c)["recording"]:
                c.call("StopRecord")
            st = _wait(c, ctx, "recording", False)
        elif args.action == "stop_streaming":
            if status(c)["streaming"]:
                c.call("StopStream")
            st = _wait(c, ctx, "streaming", False)
        else:  # set_scene: only a scene that exists
            names = status(c)["scenes"]
            match = next((n for n in names if n.lower() == args.scene.strip().lower()), None)
            if match is None:
                return ToolResult(ok=False, error=f"no scene called “{args.scene}” (scenes: {', '.join(names)})")
            c.call("SetCurrentProgramScene", {"sceneName": match})
            st = status(c)
    except ObsError as e:
        return ToolResult(ok=False, error=str(e))
    finally:
        c.close()
    want = {"start_recording": ("recording", True), "stop_recording": ("recording", False),
            "stop_streaming": ("streaming", False)}.get(args.action)
    ok = want is None or st[want[0]] == want[1]
    if args.action == "set_scene":
        ok = st["scene"].lower() == args.scene.strip().lower()
    return ToolResult(ok=True, verified=ok, data={"action": args.action, **st})


@register("obs_start_stream")
def obs_start_stream(args: NoArgs, ctx: ToolContext) -> ToolResult:
    try:
        c = connect(ctx)
        try:
            if not status(c)["streaming"]:
                c.call("StartStream")
            st = _wait(c, ctx, "streaming", True)
        finally:
            c.close()
    except ObsError as e:
        return ToolResult(ok=False, error=str(e))
    return ToolResult(ok=True, verified=st["streaming"], data={"action": "start_streaming", **st})
