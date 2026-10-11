"""Searching must not open a new tab when a search (or YouTube) tab is already open."""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from agent.browser import FakeBrowser, choose_tab, choose_youtube_tab
from agent.config import AgentConfig
from agent.launcher import FakeLauncher
from agent.server import create_app
from voice_contracts.signing import signed_headers

SECRET = b"test-secret-0123456789-abcdefghijklmnop"
BING = "https://www.bing.com/search?q=old"
YT = "https://www.youtube.com/watch?v=abc"


# ---------------------------------------------------------------- the rule itself
@pytest.mark.parametrize("urls,host,expected", [
    ([BING], "bing.com", 0),                                         # search tab open -> reuse it
    (["https://news.example/a", BING, YT], "bing.com", 1),           # find it among other tabs
    (["https://news.example/a", BING, YT], "youtube.com", 2),
    ([BING, "https://www.bing.com/search?q=newer"], "bing.com", 1),  # most recent one wins
    (["about:blank"], "bing.com", 0),                                # empty tab -> use it
    (["https://www.accuweather.com/x"], "bing.com", None),           # a page the user opened -> NEW tab, keep it
    ([], "youtube.com", None),
    (["https://notbing.com/"], "bing.com", None),                    # suffix must be a real subdomain
    (["https://m.youtube.com/watch?v=1"], "youtube.com", 0),
])
def test_choose_tab(urls, host, expected):
    assert choose_tab(urls, host) == expected


# ---------------------------------------------------------------- through the agent API
@pytest.fixture
def agent(tmp_path):
    cfg = AgentConfig.from_dict({"apps": {}, "allowed_clients": ["testclient"], "data_dir": str(tmp_path / "d")})
    browser = FakeBrowser()
    with TestClient(create_app(cfg, SECRET, FakeLauncher(), browser=browser)) as c:
        yield c, browser


def call(client, tool, payload):
    body = json.dumps(payload).encode()
    path = f"/tool/{tool}"
    return client.post(path, content=body, headers=signed_headers(SECRET, "POST", path, body)).json()


def test_repeated_search_reuses_the_search_tab(agent):
    client, b = agent
    call(client, "web_search", {"query": "weather"})
    assert len(b.tab_urls) == 1  # the blank start tab became the search tab
    call(client, "web_search", {"query": "news"})
    call(client, "web_search", {"query": "docker"})
    assert len(b.tab_urls) == 1 and "q=docker" in b.tab_urls[0]


def test_search_when_search_tab_already_open_among_others(agent):
    client, b = agent
    b.tab_urls = ["https://www.accuweather.com/x", BING, "https://github.com/"]
    call(client, "web_search", {"query": "lofi"})
    assert len(b.tab_urls) == 3 and "q=lofi" in b.tab_urls[1]
    assert b.tab_urls[0] == "https://www.accuweather.com/x"  # the user's page was not overwritten


def test_search_does_not_overwrite_a_users_page(agent):
    client, b = agent
    b.tab_urls = ["https://www.accuweather.com/x"]
    call(client, "web_search", {"query": "lofi"})
    assert b.tab_urls == ["https://www.accuweather.com/x", "https://www.bing.com/search?q=lofi"]


YT_RESULTS = "https://www.youtube.com/results?search_query=old"


@pytest.mark.parametrize("urls,playing,purpose,expected", [
    ([YT], [True], "search", None),                       # music playing -> results in a NEW tab, keep playing
    ([YT], [False], "search", 0),                         # paused player -> fine to reuse
    ([YT, YT_RESULTS], [True, False], "search", 1),       # reuse the results tab, not the player
    ([YT, YT_RESULTS], [True, False], "play", 0),         # new song replaces the one in the player tab
    ([YT_RESULTS], [False], "play", 0),                   # only a results tab -> play there
    ([BING], [False], "play", None),                      # no YouTube tab -> new tab
    (["about:blank"], [False], "search", 0),              # empty tab -> use it
    ([BING, YT, YT_RESULTS], [False, True, False], "search", 2),
])
def test_choose_youtube_tab(urls, playing, purpose, expected):
    assert choose_youtube_tab(urls, playing, purpose) == expected


def test_youtube_search_never_stops_the_music(agent):
    """Bug seen live: searching YouTube while a song played reused that tab and stopped the music."""
    client, b = agent
    call(client, "youtube_play", {"query": "lofi"})
    player = b.active
    call(client, "web_search", {"query": "landokmai", "site": "youtube"})
    assert player in b.playing and "watch?v=lofi" in b.tab_urls[player]  # still playing, untouched
    n = len(b.tab_urls)
    call(client, "web_search", {"query": "roses", "site": "youtube"})
    assert len(b.tab_urls) == n  # the results tab is reused, no tab per search


def test_play_replaces_song_in_player_tab(agent):
    client, b = agent
    call(client, "youtube_play", {"query": "lofi"})
    call(client, "web_search", {"query": "jazz", "site": "youtube"})
    n = len(b.tab_urls)
    call(client, "youtube_play", {"query": "bodyslam"})
    assert len(b.tab_urls) == n and len(b.playing) == 1  # one player, never two songs at once
    call(client, "open_result", {"index": 1})  # a YouTube result also plays in the player tab
    assert len(b.tab_urls) == n and len(b.playing) == 1


def test_open_web_result_keeps_results_tab_youtube_result_reuses_tab(agent):
    client, b = agent
    call(client, "web_search", {"query": "weather"})
    call(client, "open_result", {"index": 1})
    assert len(b.tab_urls) == 2 and "bing.com" in b.tab_urls[0]  # results stay, page opens in a new tab
    call(client, "web_search", {"query": "lofi", "site": "youtube"})
    n = len(b.tab_urls)
    call(client, "open_result", {"index": 2})
    assert len(b.tab_urls) == n and b.tab_urls[b.active].endswith("watch?v=2") and b.active in b.playing


# ---------------------------------------------------------------- real browser (opt-in, opens Chrome)
@pytest.mark.skipif(os.environ.get("VPC_LIVE_BROWSER") != "1", reason="set VPC_LIVE_BROWSER=1 to drive real Chrome")
def test_live_chrome_search_twice_keeps_one_tab(tmp_path):
    from agent.browser import PlaywrightBrowser
    b = PlaywrightBrowser(tmp_path / "profile", headless=False)
    try:
        b.search("weather in bangkok", 3)
        first = len(b.tabs("list")["tabs"])
        b.search("python asyncio", 3)
        b.search("lofi", 3)
        assert len(b.tabs("list")["tabs"]) == first == 1
        b.youtube_play("lofi hip hop")
        assert len(b.tabs("list")["tabs"]) == 2
        b.search("jazz", 3, "youtube")  # music is playing -> results in their own tab
        b.search("piano", 3, "youtube")  # ...and that results tab is reused
        assert len(b.tabs("list")["tabs"]) == 3
        playing = b._run(lambda: [p.evaluate("() => !!document.querySelector('video') && "
                                             "!document.querySelector('video').paused")
                                  for p in b._ctx.pages if "/watch" in p.url])
        assert playing == [True]  # the song kept playing through both searches
        b.youtube_play("bodyslam")
        assert len(b.tabs("list")["tabs"]) == 3  # replaced the song in the player tab
        import psutil  # Chrome must run WITH its sandbox (Playwright defaults to --no-sandbox)
        mine = [p for p in psutil.process_iter(["name", "cmdline"]) if (p.info["name"] or "").lower() == "chrome.exe"
                and str(tmp_path) in " ".join(p.info["cmdline"] or [])]
        assert mine and not any("--no-sandbox" in (p.info["cmdline"] or []) for p in mine)
    finally:
        b.close()
