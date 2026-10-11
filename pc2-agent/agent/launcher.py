"""OS boundary for launching and checking programs. Real Windows impl + fake for tests."""
from __future__ import annotations

import os
import subprocess  # nosec B404 — argv comes only from the PC2 allowlist
import sys
from typing import Protocol


class Launcher(Protocol):
    def launch(self, argv: list[str]) -> None: ...
    def open_uri(self, uri: str) -> None: ...
    def is_running(self, process: str) -> bool: ...


class WindowsLauncher:
    def launch(self, argv: list[str]) -> None:
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        # Never shell=True; argv comes from the allowlist, not from the model (§10.1, TC-S05).
        subprocess.Popen(argv, shell=False, close_fds=True, creationflags=flags,  # noqa: S603  # nosec B603
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def open_uri(self, uri: str) -> None:
        if sys.platform != "win32":
            raise RuntimeError("URI launch is only supported on Windows")
        os.startfile(uri)  # type: ignore[attr-defined]  # noqa: S606  # nosec B606 — allowlisted URI

    def is_running(self, process: str) -> bool:
        import psutil
        target = process.lower()
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() == target:
                return True
        return False


class FakeLauncher:
    def __init__(self, running: set[str] | None = None, starts: bool = True):
        self.running = {p.lower() for p in running or ()}
        self.starts = starts  # False simulates "launched but nothing appeared"
        self.launched: list[list[str]] = []
        self.uris: list[str] = []
        self.process_for_uri: dict[str, str] = {}
        self.process_for_argv0: dict[str, str] = {}
        self.keys: list[int] = []  # media/volume virtual keys sent

    def send_key(self, vk: int) -> None:
        self.keys.append(vk)

    def launch(self, argv: list[str]) -> None:
        self.launched.append(list(argv))
        if self.starts and argv[0] in self.process_for_argv0:
            self.running.add(self.process_for_argv0[argv[0]].lower())

    def open_uri(self, uri: str) -> None:
        self.uris.append(uri)
        if self.starts and uri in self.process_for_uri:
            self.running.add(self.process_for_uri[uri].lower())

    def is_running(self, process: str) -> bool:
        return process.lower() in self.running
