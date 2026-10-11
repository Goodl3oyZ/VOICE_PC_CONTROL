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

SEARCH_HOST = "bing.com"  # Google shows a CAPTCHA to automated browsers (even headed); Bing does not
SEARCH_URL = "https://www.bing.com/search?q="
RESULT_ITEM = "li.b_algo"
YT_HOST = "youtube.com"
YT_SEARCH_URL = "https://www.youtube.com/results?search_query="
YT_FIRST_VIDEO = "ytd-video-renderer a#video-title"
CAPTCHA_MARKERS = ("unusual traffic", "verify you are human", "i'm not a robot", "are you a robot",
                   "complete the security check", "captcha")


class CaptchaDetected(Exception):
    pass


class BrowserError(Exception):
    pass


class Browser(Protocol):
    def search(self, query: str, max_results: int, site: str = "web") -> list[dict[str, str]]: ...
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
        self.last_site = "web"

    # ---------------------------------------------------------------- worker thread
    def _run(self, fn: Callable[[], Any], timeout: float = 45.0) -> Any:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="agent-browser", daemon=True)
            self._thread.start()
        fut: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._jobs.put((self._retry_if_closed(fn), fut))
        return fut.result(timeout)

    def _retry_if_closed(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        """If the user closed the agent window (or Chrome crashed), relaunch and retry once."""
        def run() -> Any:
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                if not _is_closed_error(e):
                    raise
                log.info("agent browser was closed (%s); relaunching", type(e).__name__)
                self._ctx = None
                return fn()
        return run

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
            # Playwright defaults to chromium_sandbox=False, which launches Chrome with --no-sandbox
            # ("unsupported command-line flag … stability and security will suffer"). Keep the sandbox on.
            chromium_sandbox=True,
            args=["--no-first-run", "--no-default-browser-check"], viewport=None)
        self._ctx.set_default_navigation_timeout(self.nav_timeout_ms)
        self._ctx.on("close", lambda *_: setattr(self, "_ctx", None))
        return self._ctx

    def _tab_for(self, host: str) -> Any:
        """Reuse a tab already on `host` (e.g. the search or YouTube tab) instead of opening a new one."""
        ctx = self._context()
        pages = [p for p in ctx.pages if not p.is_closed()]
        i = choose_tab([p.url for p in pages], host)
        page = pages[i] if i is not None else ctx.new_page()
        page.bring_to_front()
        return page

    def _youtube_tab(self, purpose: str) -> Any:
        """search: never take over the tab that is playing; play: replace the song in the player tab."""
        ctx = self._context()
        pages = [p for p in ctx.pages if not p.is_closed()]
        playing = [_host(p.url).endswith(YT_HOST) and _video_playing(p) for p in pages]
        i = choose_youtube_tab([p.url for p in pages], playing, purpose)
        page = pages[i] if i is not None else ctx.new_page()
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
    def search(self, query: str, max_results: int = 5, site: str = "web") -> list[dict[str, str]]:
        def go() -> list[dict[str, str]]:
            if site == "youtube":
                page = self._youtube_tab("search")
                page.goto(YT_SEARCH_URL + quote_plus(query), wait_until="domcontentloaded")
                self._check_captcha(page)
                page.wait_for_selector(YT_FIRST_VIDEO, timeout=15000)
                out = []
                vids = page.locator(YT_FIRST_VIDEO)
                for i in range(min(vids.count(), max_results)):
                    a = vids.nth(i)
                    href = a.get_attribute("href") or ""
                    out.append({"title": (a.get_attribute("title") or a.inner_text() or "").strip()[:200],
                                "url": "https://www.youtube.com" + href[:300] if href.startswith("/") else href[:500],
                                "host": "youtube.com"})
                self.last_results, self.last_site = out, "youtube"
                return out
            page = self._tab_for(SEARCH_HOST)
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
            self.last_results, self.last_site = out, "web"
            return out
        return self._run(go)

    def open_result(self, index: int) -> dict[str, str]:
        if not 1 <= index <= len(self.last_results):
            raise BrowserError(f"no result #{index} (last search returned {len(self.last_results)})")
        item, site = self.last_results[index - 1], self.last_site

        def go() -> dict[str, str]:
            # YouTube result: play it in the YouTube tab. Web result: new tab, so the results tab stays.
            page = self._youtube_tab("play") if site == "youtube" else self._context().new_page()
            page.goto(item["url"], wait_until="domcontentloaded")
            self._check_captcha(page)
            page.bring_to_front()
            return {"title": (page.title() or item["title"])[:200], "url": page.url[:500], "host": _host(page.url)}
        return self._run(go)

    def youtube_play(self, query: str) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            page = self._youtube_tab("play")
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

    def close(self) -> None:
        if self._ctx is not None:
            self._run(lambda: self._ctx.close())


def _is_closed_error(e: BaseException) -> bool:
    return type(e).__name__ == "TargetClosedError" or "has been closed" in str(e)


def _video_playing(page: Any) -> bool:
    try:
        return bool(page.evaluate("() => { const v = document.querySelector('video');"
                                  " return !!v && !v.paused && !v.ended; }"))
    except Exception:  # noqa: BLE001 — a page that can't answer is treated as not playing
        return False


def _is_watch(url: str) -> bool:
    return _host(url).endswith(YT_HOST) and "/watch" in urlsplit(url).path


def choose_youtube_tab(urls: list[str], playing: list[bool], purpose: str) -> int | None:
    """YouTube tab rule. purpose="search": reuse a YouTube tab that is NOT playing (results tab), so a
    search never stops the music; purpose="play": reuse the player (watch) tab so the new song replaces
    the old one instead of two videos playing at once. None = open a new tab."""
    yt = [i for i in range(len(urls)) if (_host(urls[i]) == YT_HOST or _host(urls[i]).endswith("." + YT_HOST))]
    if purpose == "play":
        for i in reversed(yt):
            if playing[i] or _is_watch(urls[i]):
                return i
        if yt:
            return yt[-1]
    else:
        for i in reversed(yt):
            if not playing[i]:
                return i
        if yt:
            return None  # every YouTube tab is playing: results go to a new tab, music keeps playing
    return choose_tab(urls, "__no_such_host__")  # an empty tab if there is one, else None


def choose_tab(urls: list[str], host: str) -> int | None:
    """Which existing tab to reuse for `host`: a tab already on that site (most recent first), else an empty
    new tab; None means "open a new tab". Pure function so the tab rule is unit-tested."""
    for i in range(len(urls) - 1, -1, -1):
        h = _host(urls[i])
        if h == host or h.endswith("." + host):
            return i
    for i in range(len(urls) - 1, -1, -1):
        if urls[i] in ("about:blank", "chrome://newtab/", "chrome://new-tab-page/", ""):
            return i
    return None


class FakeBrowser:
    """Test double: models tabs by URL and uses the same choose_tab() rule as the real browser."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.captcha = False
        self.results = [{"title": f"Result {i}", "url": f"https://example{i}.com/", "host": f"example{i}.com"}
                        for i in range(1, 9)]
        self.last_results: list[dict[str, str]] = []
        self.last_site = "web"
        self.tab_urls: list[str] = ["about:blank"]
        self.playing: set[int] = set()  # indices of tabs with a playing video
        self.active = 0

    def _yt_tab(self, purpose: str, url: str) -> int:
        flags = [i in self.playing for i in range(len(self.tab_urls))]
        i = choose_youtube_tab(self.tab_urls, flags, purpose)
        if i is None:
            self.tab_urls.append(url)
            i = len(self.tab_urls) - 1
        else:
            self.tab_urls[i] = url
            self.playing.discard(i)
        self.active = i
        return i

    def _goto_on(self, host: str, url: str) -> None:
        i = choose_tab(self.tab_urls, host)
        if i is None:
            self.tab_urls.append(url)
            i = len(self.tab_urls) - 1
        else:
            self.tab_urls[i] = url
        self.active = i

    def search(self, query: str, max_results: int = 5, site: str = "web") -> list[dict[str, str]]:
        self.calls.append(("search", query, site))
        if self.captcha:
            raise CaptchaDetected("https://www.bing.com/challenge")
        if site == "youtube":
            self._yt_tab("search", YT_SEARCH_URL + quote_plus(query))
            self.last_results = [{"title": f"{query} video {i}", "url": f"https://www.youtube.com/watch?v={i}",
                                  "host": "youtube.com"} for i in range(1, max_results + 1)]
        else:
            self._goto_on(SEARCH_HOST, SEARCH_URL + quote_plus(query))
            self.last_results = self.results[:max_results]
        self.last_site = site
        return self.last_results

    def open_result(self, index: int) -> dict[str, str]:
        self.calls.append(("open_result", index))
        if not 1 <= index <= len(self.last_results):
            raise BrowserError(f"no result #{index} (last search returned {len(self.last_results)})")
        item = self.last_results[index - 1]
        if self.last_site == "youtube":
            self.playing.add(self._yt_tab("play", item["url"]))
        else:
            self.tab_urls.append(item["url"])
            self.active = len(self.tab_urls) - 1
        return dict(item)

    def youtube_play(self, query: str) -> dict[str, Any]:
        self.calls.append(("youtube_play", query))
        self.playing.add(self._yt_tab("play", "https://www.youtube.com/watch?v=" + quote_plus(query)))
        return {"title": f"{query} (official video)", "url": "https://www.youtube.com/watch?v=x", "playing": True,
                "position_s": 3.0}

    def tabs(self, action: str) -> dict[str, Any]:
        self.calls.append(("tabs", action))
        if action == "close" and self.tab_urls:
            self.tab_urls.pop(self.active)
            self.playing = {i if i < self.active else i - 1 for i in self.playing if i != self.active}
            self.active = max(0, len(self.tab_urls) - 1)
        elif action in ("next", "previous") and self.tab_urls:
            self.active = (self.active + (1 if action == "next" else -1)) % len(self.tab_urls)
        return {"tabs": [{"title": u, "host": _host(u)} for u in self.tab_urls]}
