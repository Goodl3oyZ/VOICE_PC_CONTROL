"""Everyday-Chrome connector (redesign step 2): the "Voice PC" extension in the user's own Chrome.

Replaces the separate automated browser, where YouTube videos would not play and Google showed CAPTCHAs.

Trust boundary:
- The bridge listens on 127.0.0.1 only. The extension proves itself with a random token kept in the agent's
  data dir (pasted once into the extension's options page) and must come from a chrome-extension:// origin.
  A web page or another local program without the token gets nothing.
- The extension exposes a FIXED set of operations (list/open/activate/close tabs, read search results,
  video state/play) with no "run this script" operation, and only navigates to https URLs. Every
  decision (which tab to reuse, what to open) is made here, in Python, and unit-tested.
- Page text that comes back (titles, results) stays untrusted: the tools mark their results untrusted.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit

from .browser import BrowserError, CaptchaDetected, choose_tab, choose_youtube_tab

log = logging.getLogger("pc2.extension")

GOOGLE_HOST = "google.com"
GOOGLE_SEARCH_URL = "https://www.google.com/search?q="
YT_HOST = "youtube.com"
YT_SEARCH_URL = "https://www.youtube.com/results?search_query="
NOT_CONNECTED = ("Chrome on PC2 is not connected: open Chrome and check that the Voice PC extension is on "
                 "(chrome://extensions)")


def load_token(data_dir: Path) -> str:
    """The extension's pairing token (created on first use; only the PC2 user can read the data dir)."""
    p = data_dir / "extension_token"
    if not p.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


class ExtensionBridge:
    """One live connection to the extension; tool threads call it synchronously."""

    def __init__(self, token: str, call_timeout: float = 30.0):
        self._token = token
        self.call_timeout = call_timeout
        self._ws: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._seq = 0
        self.connected_at: float | None = None
        self.version = ""

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def serve(self, host: str = "127.0.0.1", port: int = 8766) -> None:
        from websockets.asyncio.server import serve

        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("the extension bridge must listen on localhost only")
        self._loop = asyncio.get_running_loop()
        async with serve(self._handler, host, port, max_size=2 ** 20, ping_interval=20,
                         process_request=self._check_origin):
            log.info("extension bridge on ws://%s:%d", host, port)
            await asyncio.Future()  # forever

    @staticmethod
    def _check_origin(connection: Any, request: Any) -> Any:
        origin = request.headers.get("Origin", "")
        if not origin.startswith("chrome-extension://"):
            return connection.respond(403, "extension only\n")
        return None

    async def _handler(self, ws: Any) -> None:
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
        except (TimeoutError, ValueError):
            return
        if hello.get("type") != "hello" or not hmac.compare_digest(str(hello.get("token", "")), self._token):
            log.warning("extension handshake rejected")
            await ws.send(json.dumps({"type": "rejected", "reason": "wrong token"}))
            await asyncio.sleep(1)  # slow down guessing
            return
        if self._ws is not None:  # a reloaded extension replaces the old connection
            await self._ws.close()
        self._ws, self.connected_at, self.version = ws, time.time(), str(hello.get("version", ""))[:20]
        await ws.send(json.dumps({"type": "welcome"}))
        log.info("Chrome extension connected (v%s)", self.version)
        pinger = asyncio.create_task(self._ping(ws))
        try:
            async for raw in ws:
                msg = json.loads(raw)
                fut = self._pending.pop(str(msg.get("id")), None)
                if fut is not None and not fut.done():
                    fut.set_result(msg)
        except Exception as e:  # noqa: BLE001 — a dropped connection is normal (Chrome closed)
            log.info("extension connection ended: %s", type(e).__name__)
        finally:
            pinger.cancel()
            if self._ws is ws:
                self._ws = None
                for f in self._pending.values():
                    if not f.done():
                        f.set_exception(BrowserError(NOT_CONNECTED))
                self._pending.clear()

    @staticmethod
    async def _ping(ws: Any, every: float = 10.0) -> None:
        """App-level ping: messages (not protocol pings) keep Chrome's extension worker from being suspended."""
        while True:
            await asyncio.sleep(every)
            await ws.send('{"type":"ping"}')

    async def acall(self, op: str, timeout: float | None = None, **args: Any) -> Any:
        if self._ws is None:
            raise BrowserError(NOT_CONNECTED)
        self._seq += 1
        mid = str(self._seq)
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send(json.dumps({"id": mid, "op": op, "args": args}))
        try:
            msg = await asyncio.wait_for(fut, timeout or self.call_timeout)
        except TimeoutError as e:
            self._pending.pop(mid, None)
            raise BrowserError(f"Chrome did not answer ({op})") from e
        if not msg.get("ok"):
            err = str(msg.get("error", "failed"))[:300]
            if msg.get("captcha"):
                raise CaptchaDetected(err)
            raise BrowserError(err)
        return msg.get("data")

    def call(self, op: str, timeout: float | None = None, **args: Any) -> Any:
        """From a tool thread (tools run in asyncio.to_thread)."""
        if self._loop is None:
            raise BrowserError(NOT_CONNECTED)
        fut = asyncio.run_coroutine_threadsafe(self.acall(op, timeout, **args), self._loop)
        return fut.result((timeout or self.call_timeout) + 5)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class ExtensionBrowser:
    """The Browser protocol (search/open_result/youtube_play/tabs) on the user's own Chrome."""

    def __init__(self, bridge: Any, sleep: Any = time.sleep):
        self.bridge, self.sleep = bridge, sleep
        self.last_results: list[dict[str, str]] = []
        self.last_site = "web"

    def _tabs(self) -> list[dict[str, Any]]:
        return list(self.bridge.call("tabs.list") or [])

    def _open(self, url: str, tab: dict[str, Any] | None) -> dict[str, Any]:
        if not url.startswith("https://"):
            raise BrowserError("only https pages can be opened")
        return dict(self.bridge.call("tabs.open", url=url, tabId=tab["id"] if tab else None, timeout=25))

    def _youtube_tab(self, purpose: str) -> dict[str, Any] | None:
        tabs = self._tabs()
        i = choose_youtube_tab([t["url"] for t in tabs], [bool(t.get("audible")) for t in tabs], purpose)
        return tabs[i] if i is not None else None

    def search(self, query: str, max_results: int = 5, site: str = "web") -> list[dict[str, str]]:
        # A failed search must not leave the previous results behind ("open result 1" would open the old one)
        self.last_results = []
        if site == "youtube":
            tab = self._open(YT_SEARCH_URL + quote_plus(query), self._youtube_tab("search"))
            out = self.bridge.call("page.results", tabId=tab["id"], kind="youtube", max=max_results, timeout=20)
        else:
            tabs = self._tabs()
            i = choose_tab([t["url"] for t in tabs], GOOGLE_HOST)
            tab = self._open(GOOGLE_SEARCH_URL + quote_plus(query), tabs[i] if i is not None else None)
            out = self.bridge.call("page.results", tabId=tab["id"], kind="google", max=max_results, timeout=20)
        results = [{k: str(v)[:500] for k, v in r.items()} for r in (out or [])[:max_results]
                   if isinstance(r, dict) and str(r.get("url", "")).startswith("https://")]
        self.last_results, self.last_site = results, site if site == "youtube" else "web"
        return results

    def open_result(self, index: int) -> dict[str, str]:
        if not 1 <= index <= len(self.last_results):
            raise BrowserError(f"no result #{index} (last search returned {len(self.last_results)})")
        item = self.last_results[index - 1]
        # YouTube: play in the player tab. Web: a new tab, so the results stay open.
        if self.last_site == "youtube":
            tab = self._open(item["url"], self._youtube_tab("play"))
            self._ensure_playing(tab)
        else:
            tab = self._open(item["url"], None)
        return {"title": str(tab.get("title") or item.get("title", ""))[:200], "url": str(tab.get("url", ""))[:500],
                "host": _host(str(tab.get("url", "")))}

    def _ensure_playing(self, tab: dict[str, Any]) -> dict[str, Any]:
        state: dict[str, Any] = {}
        for attempt in range(6):  # the player needs a moment after navigation
            self.sleep(1.0)
            state = dict(self.bridge.call("video.state", tabId=tab["id"]) or {})
            if state.get("exists") and not state.get("paused"):
                return state
            if state.get("exists") and attempt >= 1:
                self.bridge.call("video.play", tabId=tab["id"])
        return state

    def youtube_play(self, query: str) -> dict[str, Any]:
        player = self._youtube_tab("play")
        tab = self._open(YT_SEARCH_URL + quote_plus(query), player)
        found = self.bridge.call("page.results", tabId=tab["id"], kind="youtube", max=1, timeout=20) or []
        if not found or not str(found[0].get("url", "")).startswith("https://www.youtube.com/"):
            raise BrowserError(f"no YouTube video found for “{query[:80]}”")
        first = found[0]
        tab = self._open(first["url"], tab)
        state = self._ensure_playing(tab)
        return {"title": str(first.get("title", ""))[:200], "url": str(tab.get("url", ""))[:500],
                "channel": str(first.get("channel", ""))[:100], "playing": bool(state.get("exists")
                                                                              and not state.get("paused")),
                "position_s": round(float(state.get("time") or 0), 1)}

    def tabs(self, action: str) -> dict[str, Any]:
        tabs = self._tabs()
        if action != "list" and not tabs:
            raise BrowserError("no tabs open")
        active = next((i for i, t in enumerate(tabs) if t.get("active") and t.get("focused")),
                      next((i for i, t in enumerate(tabs) if t.get("active")), len(tabs) - 1))
        if action in ("next", "previous"):
            target = tabs[(active + (1 if action == "next" else -1)) % len(tabs)]
            self.bridge.call("tabs.activate", tabId=target["id"])
        elif action == "close":
            self.bridge.call("tabs.close", tabId=tabs[active]["id"])
        if action != "list":
            tabs = self._tabs()
        return {"tabs": [{"title": str(t.get("title") or "")[:120], "host": _host(str(t.get("url", "")))}
                         for t in tabs]}

    def close(self) -> None:
        """Nothing to close: it is the user's own Chrome."""
