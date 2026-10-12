"""Redesign step 2: the user's own Chrome through the Voice PC extension (bridge + browser logic)."""
from __future__ import annotations

import asyncio
import json

import pytest

from agent.browser import BrowserError, CaptchaDetected
from agent.extension import ExtensionBridge, ExtensionBrowser, load_token


class FakeChrome:
    """Scripted extension: tabs in one window, results per tab kind, a video that may start paused."""

    def __init__(self, tabs=None, video_paused=False):
        self.tabs = tabs or [{"id": 1, "url": "chrome://newtab/", "title": "New Tab", "active": True,
                              "audible": False, "focused": True}]
        self.calls: list[tuple[str, dict]] = []
        self.video = {"exists": True, "paused": video_paused, "time": 3.0}
        self.next_id = 100
        self.captcha = False
        self.logged_in = True
        self.connected = True

    def call(self, op, timeout=None, **a):
        self.calls.append((op, a))
        if op == "tabs.list":
            return [dict(t) for t in self.tabs]
        if op == "tabs.open":
            if a["tabId"] is None:
                self.next_id += 1
                tab = {"id": self.next_id, "active": True, "audible": False, "focused": True}
                self.tabs.append(tab)
            else:
                tab = next(t for t in self.tabs if t["id"] == a["tabId"])
            tab.update(url=a["url"], title="page")
            return dict(tab)
        if op == "page.results":
            if self.captcha:
                raise CaptchaDetected("google sorry")
            if a["kind"] == "youtube":
                return [{"title": "Lofi radio", "url": "https://www.youtube.com/watch?v=abc", "channel": "Lofi Girl",
                         "length": "LIVE"}][: a["max"]]
            return [{"title": "Flights", "url": "https://example.com/f", "host": "example.com"},
                    {"title": "Evil", "url": "javascript:alert(1)", "host": "x"}]
        if op == "video.state":
            return dict(self.video)
        if op == "video.play":
            self.video["paused"] = False
            return dict(self.video)
        if op == "video.skip_ad":
            return {"ad": True, "skipped": True}
        if op == "social.state":
            return {"loggedIn": self.logged_in}
        if op == "social.act":
            return {"ok": True}
        if op in ("tabs.activate", "tabs.close"):
            if op == "tabs.close":
                self.tabs = [t for t in self.tabs if t["id"] != a["tabId"]]
            return {}
        raise AssertionError(op)


def browser(chrome):
    return ExtensionBrowser(chrome, sleep=lambda s: None)


def ops(chrome):
    return [c[0] for c in chrome.calls]


def test_google_search_reuses_the_empty_tab_and_drops_non_https_results():
    chrome = FakeChrome()
    out = browser(chrome).search("cheap flights", 5)
    assert out == [{"title": "Flights", "url": "https://example.com/f", "host": "example.com"}]
    opened = [a for op, a in chrome.calls if op == "tabs.open"][0]
    assert opened["tabId"] == 1 and opened["url"].startswith("https://www.google.com/search?q=cheap+flights")


def test_youtube_search_never_takes_over_the_playing_tab():
    chrome = FakeChrome(tabs=[{"id": 7, "url": "https://www.youtube.com/watch?v=song", "title": "song",
                               "active": True, "audible": True, "focused": True}])
    b = browser(chrome)
    b.search("jazz", 5, site="youtube")
    opened = [a for op, a in chrome.calls if op == "tabs.open"][0]
    assert opened["tabId"] is None  # a new tab: the music keeps playing
    assert b.last_site == "youtube" and b.last_results[0]["channel"] == "Lofi Girl"


def test_youtube_play_replaces_the_player_and_presses_play_if_paused():
    chrome = FakeChrome(tabs=[{"id": 7, "url": "https://www.youtube.com/watch?v=old", "title": "old",
                               "active": True, "audible": True, "focused": True}], video_paused=True)
    r = browser(chrome).youtube_play("lofi")
    opens = [a for op, a in chrome.calls if op == "tabs.open"]
    assert [o["tabId"] for o in opens] == [7, 7] and opens[1]["url"] == "https://www.youtube.com/watch?v=abc"
    assert "video.play" in ops(chrome) and r["playing"] and r["channel"] == "Lofi Girl"


def test_open_result_web_uses_a_new_tab_and_youtube_the_player():
    chrome = FakeChrome()
    b = browser(chrome)
    b.search("x", 5)
    b.open_result(1)
    assert [a for op, a in chrome.calls if op == "tabs.open"][-1]["tabId"] is None
    with pytest.raises(BrowserError, match="no result #2"):
        b.open_result(2)


def test_only_https_is_ever_opened():
    with pytest.raises(BrowserError, match="https"):
        browser(FakeChrome())._open("file:///C:/Users/x/secret.txt", None)


def test_captcha_is_reported_not_solved():
    chrome = FakeChrome()
    b = browser(chrome)
    b.search("x", 5, site="youtube")
    chrome.captcha = True
    with pytest.raises(CaptchaDetected):
        b.search("x", 5)
    with pytest.raises(BrowserError, match="no result #1"):  # live bug: opened the earlier YouTube result
        b.open_result(1)


def test_tabs_next_and_close():
    chrome = FakeChrome(tabs=[{"id": 1, "url": "https://a.com/", "title": "A", "active": True, "audible": False,
                               "focused": True},
                              {"id": 2, "url": "https://b.com/", "title": "B", "active": False, "audible": False,
                               "focused": True}])
    b = browser(chrome)
    b.tabs("next")
    assert ("tabs.activate", {"tabId": 2}) in chrome.calls
    out = b.tabs("close")
    assert ("tabs.close", {"tabId": 1}) in chrome.calls and [t["host"] for t in out["tabs"]] == ["b.com"]


def test_token_is_created_once_and_kept(tmp_path):
    t = load_token(tmp_path)
    assert len(t) >= 40 and load_token(tmp_path) == t


# ------------------------------------------------------------------ real WebSocket bridge
async def _bridge(port_holder):
    from websockets.asyncio.server import serve
    bridge = ExtensionBridge("tok-" + "x" * 40, call_timeout=2)
    bridge._loop = asyncio.get_running_loop()
    server = await serve(bridge._handler, "127.0.0.1", 0, process_request=bridge._check_origin).__aenter__()
    port_holder.append(server.sockets[0].getsockname()[1])
    return bridge, server


async def test_bridge_round_trip_and_auth():
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    port: list[int] = []
    bridge, server = await _bridge(port)
    url = f"ws://127.0.0.1:{port[0]}/"
    try:
        with pytest.raises(InvalidStatus):  # a web page or local program without an extension origin
            async with connect(url, origin="https://evil.example"):
                pass
        async with connect(url, origin="chrome-extension://abc") as ws:
            await ws.send(json.dumps({"type": "hello", "token": "wrong"}))
            assert json.loads(await ws.recv())["type"] == "rejected"
        assert not bridge.connected
        with pytest.raises(BrowserError, match="not connected"):
            await bridge.acall("tabs.list")

        async with connect(url, origin="chrome-extension://abc") as ws:
            await ws.send(json.dumps({"type": "hello", "token": "tok-" + "x" * 40, "version": "0.1.0"}))
            assert json.loads(await ws.recv())["type"] == "welcome"

            async def extension():
                msg = json.loads(await ws.recv())
                assert msg["op"] == "tabs.list"
                await ws.send(json.dumps({"id": msg["id"], "ok": True, "data": [{"id": 1}]}))
                msg = json.loads(await ws.recv())
                await ws.send(json.dumps({"id": msg["id"], "ok": False, "error": "human check", "captcha": True}))

            task = asyncio.create_task(extension())
            assert await bridge.acall("tabs.list") == [{"id": 1}]
            with pytest.raises(CaptchaDetected):
                await bridge.acall("page.results", tabId=1, kind="google", max=5)
            await task
            assert bridge.connected and bridge.version == "0.1.0"
    finally:
        server.close()


def test_bridge_refuses_to_listen_beyond_localhost():
    with pytest.raises(ValueError, match="localhost"):
        asyncio.run(ExtensionBridge("t").serve("0.0.0.0", 0))  # noqa: S104 — the point of the test


# ------------------------------------------------------------------ social (step 4)
def test_social_open_builds_fixed_urls_and_reuses_the_site_tab():
    chrome = FakeChrome(tabs=[{"id": 3, "url": "https://x.com/home", "title": "X", "active": False, "audible": False,
                               "focused": True}])
    b = browser(chrome)
    b.social_open("x", "search", "ai news")
    b.social_open("instagram", "profile", "@some.user")
    opens = [a for op, a in chrome.calls if op == "tabs.open"]
    assert opens[0] == {"url": "https://x.com/search?q=ai+news", "tabId": 3}
    assert opens[1]["url"] == "https://www.instagram.com/some.user/" and opens[1]["tabId"] is None


def test_social_stops_on_a_login_page():
    chrome = FakeChrome()
    chrome.logged_in = False
    with pytest.raises(BrowserError, match="not logged in"):
        browser(chrome).social_open("facebook", "feed")


def test_social_act_goes_to_the_right_page_first():
    chrome = FakeChrome()
    b = browser(chrome)
    b.social_act("x", "message", "hi", to="@friend_1")
    assert [a["url"] for op, a in chrome.calls if op == "tabs.open"] == ["https://x.com/friend_1"]
    act = [a for op, a in chrome.calls if op == "social.act"][0]
    assert act["action"] == "message" and act["text"] == "hi" and act["dry"] is False
    with pytest.raises(BrowserError, match="open the Tiktok post"):
        browser(FakeChrome()).social_act("tiktok", "like")


def test_skip_ad_uses_the_player_tab():
    chrome = FakeChrome(tabs=[{"id": 7, "url": "https://www.youtube.com/watch?v=a", "title": "v", "active": True,
                               "audible": True, "focused": True}])
    assert browser(chrome).youtube_skip_ad() == {"ad": True, "skipped": True}
    assert ("video.skip_ad", {"tabId": 7}) in chrome.calls
    with pytest.raises(BrowserError, match="no YouTube video"):
        browser(FakeChrome()).youtube_skip_ad()
