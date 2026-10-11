"""Agent browser (Phase 2, doc §3.4, US-301..305): Playwright driving the installed Chrome with a
DEDICATED profile under the agent's data dir — never the user's logged-in profile (US-304).

Playwright's sync API is bound to the thread that started it, so one worker thread owns the browser and
all calls are marshalled to it. The window is visible on PC2 (headed): the user can see what the AI does,
and search engines serve normal pages instead of bot challenges. CAPTCHAs are detected and reported,
never bypassed (US-305).
"""
from __future__ import annotations

import concurrent.futures
import logging
import queue
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus, urlsplit

log = logging.getLogger("pc2.browser")

SEARCH_URL = "https://www.bing.com/search?q="
RESULT_ITEM = "li.b_algo"
YT_SEARCH_URL = "https://www.youtube.com/results?search_query="
YT_FIRST_VIDEO = "ytd-video-renderer a#video-title"
CAPTCHA_MARKERS = ("unusual traffic", "verify you are human", "i'm not a robot", "are you a robot",
                   "complete the security check", "captcha")


class CaptchaDetected(Exception):
    pass


class BrowserError(Exception):
    pass


class Browser(Protocol):
    def search(self, query: str, max_results: int) -> list[dict[str, str]]: ...
    def open_result(self, index: int) -> dict[str, str]: ...
    def youtube_play(self, query: str) -> dict[str, Any]: ...
    def tabs(self, action: str) -> dict[str, Any]: ...


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _display_host(shown: str) -> str:
    """"https://www.accuweather.com › en › th" -> "www.accuweather.com" (display only, never navigated to)."""
    s = re.sub(r"^https?://", "", shown.strip(), flags=re.I)
    s = re.split(r"[\s/›]", s, maxsplit=1)[0]
    return s.lower() if "." in s and len(s) <= 100 else ""


class PlaywrightBrowser:
    def __init__(self, profile_dir: Path, headless: bool = False, channel: str = "chrome",
                 nav_timeout_ms: int = 20000):
        self.profile_dir, self.headless = profile_dir, headless
        self.channel, self.nav_timeout_ms = channel, nav_timeout_ms
        self._jobs: queue.Queue[tuple[Callable[[], Any], concurrent.futures.Future[Any]]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ctx: Any = None
        self._pw: Any = None
        self.last_results: list[dict[str, str]] = []

    # ---------------------------------------------------------------- worker thread
    def _run(self, fn: Callable[[], Any], timeout: float = 45.0) -> Any:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="agent-browser", daemon=True)
            self._thread.start()
        fut: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._jobs.put((fn, fut))
        return fut.result(timeout)

    def _loop(self) -> None:
        while True:
            fn, fut = self._jobs.get()
            try:
                fut.set_result(fn())
            except Exception as e:  # noqa: BLE001 — delivered to the caller
                fut.set_exception(e)

    def _context(self) -> Any:
        """Persistent context in the agent profile; relaunched if the user closed the window."""
        if self._ctx is not None:
            try:
                _ = self._ctx.pages  # raises if the browser is gone
                return self._ctx
            except Exception:  # noqa: BLE001
                self._ctx = None
        from playwright.sync_api import sync_playwright
        if self._pw is None:
            self._pw = sync_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(self.profile_dir), channel=self.channel, headless=self.headless,
            args=["--no-first-run", "--no-default-browser-check"], viewport=None)
        self._ctx.set_default_navigation_timeout(self.nav_timeout_ms)
        self._ctx.on("close", lambda *_: setattr(self, "_ctx", None))
        return self._ctx

    def _page(self) -> Any:
        ctx = self._context()
        pages = [p for p in ctx.pages if not p.is_closed()]
        page = pages[-1] if pages else ctx.new_page()
        page.bring_to_front()
        return page

    @staticmethod
    def _check_captcha(page: Any) -> None:
        url = page.url.lower()
        if "/sorry/" in url or "captcha" in url or "challenge" in url:
            raise CaptchaDetected(url)
        if page.locator("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile']").count():
            raise CaptchaDetected(url)
        body = (page.locator("body").inner_text(timeout=3000) or "")[:4000].lower()
        if any(m in body for m in CAPTCHA_MARKERS) and page.locator("a").count() < 15:
            raise CaptchaDetected(url)

    # ---------------------------------------------------------------- tools
    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        def go() -> list[dict[str, str]]:
            page = self._page()
            page.goto(SEARCH_URL + quote_plus(query), wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            self._check_captcha(page)
            out = []
            items = page.locator(RESULT_ITEM)
            for i in range(items.count()):
                if len(out) >= max_results:
                    break
                li = items.nth(i)
                a = li.locator("h2 a").first
                if not a.count():
                    continue
                href = a.get_attribute("href") or ""
                if not href.startswith("https://"):
                    continue
                # Bing hrefs are click-tracking redirects; the <cite> shows the real destination for display.
                cite = li.locator("cite").first
                shown = cite.inner_text().strip() if cite.count() else ""
                out.append({"title": (a.inner_text() or "").strip()[:200], "url": href[:1000],
                            "host": _display_host(shown) or _host(href)})
            self.last_results = out
            return out
        return self._run(go)

    def open_result(self, index: int) -> dict[str, str]:
        if not 1 <= index <= len(self.last_results):
            raise BrowserError(f"no result #{index} (last search returned {len(self.last_results)})")
        item = self.last_results[index - 1]

        def go() -> dict[str, str]:
            page = self._context().new_page()
            page.goto(item["url"], wait_until="domcontentloaded")
            self._check_captcha(page)
            return {"title": (page.title() or item["title"])[:200], "url": page.url[:500], "host": _host(page.url)}
        return self._run(go)

    def youtube_play(self, query: str) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            page = self._page()
            page.goto(YT_SEARCH_URL + quote_plus(query), wait_until="domcontentloaded")
            self._check_captcha(page)
            page.wait_for_selector(YT_FIRST_VIDEO, timeout=15000)
            first = page.locator(YT_FIRST_VIDEO).first
            title = (first.get_attribute("title") or first.inner_text() or "").strip()[:200]
            first.click()
            page.wait_for_selector("video", timeout=15000)
            page.wait_for_timeout(2500)
            state = page.evaluate("() => { const v = document.querySelector('video');"
                                  " return v ? [v.paused, v.currentTime] : [true, 0]; }")
            if state[0]:  # autoplay blocked: press play once
                page.evaluate("() => document.querySelector('video')?.play()")
                page.wait_for_timeout(1500)
                state = page.evaluate("() => { const v = document.querySelector('video');"
                                      " return v ? [v.paused, v.currentTime] : [true, 0]; }")
            return {"title": title, "url": page.url[:500], "playing": not state[0], "position_s": round(state[1], 1)}
        return self._run(go)

    def tabs(self, action: str) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            ctx = self._context()
            pages = [p for p in ctx.pages if not p.is_closed()]
            if action != "list" and not pages:
                raise BrowserError("no tabs open")
            if action in ("next", "previous") and pages:
                cur = next((i for i, p in enumerate(pages) if p.evaluate("document.visibilityState") == "visible"),
                           len(pages) - 1)
                target = pages[(cur + (1 if action == "next" else -1)) % len(pages)]
                target.bring_to_front()
            elif action == "close" and pages:
                visible = [p for p in pages if p.evaluate("document.visibilityState") == "visible"]
                (visible[0] if visible else pages[-1]).close()
            pages = [p for p in ctx.pages if not p.is_closed()]
            return {"tabs": [{"title": (p.title() or "")[:120], "host": _host(p.url)} for p in pages]}
        return self._run(go)


class FakeBrowser:
    """Test double with the same behaviour contract (results memory, captcha, playing state)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.captcha = False
        self.results = [{"title": f"Result {i}", "url": f"https://example{i}.com/", "host": f"example{i}.com"}
                        for i in range(1, 9)]
        self.last_results: list[dict[str, str]] = []
        self.open_tabs = ["New Tab"]

    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        self.calls.append(("search", query))
        if self.captcha:
            raise CaptchaDetected("https://www.bing.com/challenge")
        self.last_results = self.results[:max_results]
        return self.last_results

    def open_result(self, index: int) -> dict[str, str]:
        self.calls.append(("open_result", index))
        if not 1 <= index <= len(self.last_results):
            raise BrowserError(f"no result #{index} (last search returned {len(self.last_results)})")
        self.open_tabs.append(self.last_results[index - 1]["title"])
        return dict(self.last_results[index - 1])

    def youtube_play(self, query: str) -> dict[str, Any]:
        self.calls.append(("youtube_play", query))
        return {"title": f"{query} (official video)", "url": "https://www.youtube.com/watch?v=x", "playing": True,
                "position_s": 3.0}

    def tabs(self, action: str) -> dict[str, Any]:
        self.calls.append(("tabs", action))
        if action == "close" and self.open_tabs:
            self.open_tabs.pop()
        return {"tabs": [{"title": t, "host": ""} for t in self.open_tabs]}
