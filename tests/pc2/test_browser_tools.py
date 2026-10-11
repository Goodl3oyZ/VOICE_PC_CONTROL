"""Phase 2 browser tools on PC2 (with FakeBrowser) + PC1 summaries/taint for them."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agent.browser import FakeBrowser
from agent.config import AgentConfig
from agent.launcher import FakeLauncher
from agent.server import create_app
from voice_contracts.signing import signed_headers

SECRET = b"test-secret-0123456789-abcdefghijklmnop"


@pytest.fixture
def agent(tmp_path):
    cfg = AgentConfig.from_dict({"apps": {}, "allowed_clients": ["testclient"], "data_dir": str(tmp_path / "d")})
    browser = FakeBrowser()
    with TestClient(create_app(cfg, SECRET, FakeLauncher(), browser=browser)) as c:
        yield c, browser


def call(client, path, payload):
    body = json.dumps(payload).encode()
    return client.post(path, content=body, headers=signed_headers(SECRET, "POST", path, body)).json()


def test_web_search_returns_untrusted_results(agent):
    client, browser = agent
    r = call(client, "/tool/web_search", {"query": "weather bangkok", "max_results": 3})
    assert r["ok"] and r["verified"] and r["untrusted"] is True
    assert [x["title"] for x in r["data"]["results"]] == ["Result 1", "Result 2", "Result 3"]


def test_open_result_uses_last_search(agent):
    client, browser = agent
    assert "no result #2" in call(client, "/tool/open_result", {"index": 2})["error"]  # nothing searched yet
    call(client, "/tool/web_search", {"query": "x"})
    r = call(client, "/tool/open_result", {"index": 2})
    assert r["ok"] and r["data"]["url"] == "https://example2.com/" and r["untrusted"]


def test_youtube_play_verified_only_when_playing(agent):
    client, browser = agent
    r = call(client, "/tool/youtube_play", {"query": "lofi"})
    assert r["ok"] and r["verified"] and r["data"]["playing"] is True
    browser.youtube_play = lambda q: {"title": "x", "url": "u", "playing": False}
    r = call(client, "/tool/youtube_play", {"query": "lofi"})
    assert not r["verified"] and "not playing" in r["error"]


@pytest.mark.security
def test_captcha_stops_and_reports(agent):
    client, browser = agent
    browser.captcha = True
    r = call(client, "/tool/web_search", {"query": "x"})
    assert not r["ok"] and r["data"]["captcha"] is True and "CAPTCHA" in r["error"]


def test_tabs(agent):
    client, browser = agent
    call(client, "/tool/web_search", {"query": "x"})
    call(client, "/tool/open_result", {"index": 1})
    assert len(call(client, "/tool/browser_tabs", {"action": "list"})["data"]["tabs"]) == 2
    assert len(call(client, "/tool/browser_tabs", {"action": "close"})["data"]["tabs"]) == 1


@pytest.mark.security
@pytest.mark.parametrize("path,payload", [
    ("/tool/open_result", {"index": 0}), ("/tool/open_result", {"index": 99}),
    ("/tool/open_result", {"url": "https://evil.example"}), ("/tool/web_search", {"query": "x", "max_results": 50}),
    ("/tool/browser_tabs", {"action": "close_all"}), ("/tool/youtube_play", {"query": ""}),
])
def test_bad_args_denied_by_policy(agent, path, payload):
    client, browser = agent
    r = call(client, path, payload)
    assert r["error"].startswith("policy deny") and browser.calls == []


# ---------------------------------------------------------------- PC1 side
async def test_pc1_summary_and_taint(rig_factory):
    from voice_contracts.models import ToolResult
    rig = rig_factory(language="en")
    rig.pc2.handlers["web_search"] = lambda a: ToolResult(ok=True, verified=True, untrusted=True, data={
        "results": [{"title": "AccuWeather Bangkok", "host": "accuweather.com", "url": "https://accuweather.com/x"},
                    {"title": "BBC Weather", "host": "bbc.com", "url": "https://bbc.com/w"}]})
    job = await rig.run_text("Search for weather in Bangkok")
    assert job.summary.startswith("Results for “weather in Bangkok” (Bing): 1) AccuWeather Bangkok — accuweather.com")
    assert job.tainted is True  # web content is untrusted data


async def test_pc1_youtube_and_captcha_summaries(rig_factory):
    from voice_contracts.models import ToolResult
    rig = rig_factory(language="en")
    rig.pc2.handlers["youtube_play"] = lambda a: ToolResult(ok=True, verified=True, untrusted=True,
                                                             data={"title": "Lofi Girl radio", "playing": True})
    assert (await rig.run_text("play lofi")).summary == "Playing “Lofi Girl radio” on YouTube"
    rig.pc2.handlers["web_search"] = lambda a: ToolResult(ok=False, error="CAPTCHA", data={"captcha": True})
    job = await rig.run_text("search something")
    assert job.state.value == "failed" and job.summary.startswith("CAPTCHA detected")
