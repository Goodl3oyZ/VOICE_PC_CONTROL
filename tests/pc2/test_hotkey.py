"""US-607: local kill switch hotkey on PC2 (no network needed)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agent.browser import FakeBrowser
from agent.config import AgentConfig
from agent.hotkey import parse_hotkey, toggle_kill
from agent.launcher import FakeLauncher
from agent.server import create_app
from voice_contracts.signing import signed_headers

SECRET = b"test-secret-0123456789-abcdefghijklmnop"


@pytest.mark.parametrize("spec,expected", [
    ("ctrl+alt+shift+k", (0x0007, ord("K"))),
    ("Ctrl + Alt + Pause", (0x0003, 0x13)),
    ("win+f12", (0x0008, 0x7B)),
])
def test_parse_hotkey(spec, expected):
    assert parse_hotkey(spec) == expected


@pytest.mark.parametrize("spec", ["k", "ctrl+", "hyper+k", "ctrl+alt+nokey"])
def test_parse_hotkey_rejects(spec):
    with pytest.raises(ValueError):
        parse_hotkey(spec)


def test_hotkey_engages_and_releases_the_kill_switch(tmp_path):
    cfg = AgentConfig.from_dict({"apps": {"notepad": {"process": "notepad.exe", "argv": ["notepad.exe"]}},
                                 "allowed_clients": ["testclient"], "data_dir": str(tmp_path),
                                 "verify_timeout_s": 0.2})
    launcher = FakeLauncher()
    launcher.process_for_argv0 = {"notepad.exe": "notepad.exe"}
    app = create_app(cfg, SECRET, launcher, sleep=lambda s: None, browser=FakeBrowser())

    def open_notepad(client):
        body = json.dumps({"app": "notepad"}).encode()
        return client.post("/tool/open_app", content=body,
                           headers=signed_headers(SECRET, "POST", "/tool/open_app", body)).json()

    with TestClient(app) as client:
        assert toggle_kill(app) is True
        assert app.state.ctx.cancel.is_set()  # anything running is told to stop
        r = open_notepad(client)
        assert not r["ok"] and "kill switch" in r["error"] and launcher.launched == []
        assert (tmp_path / "killswitch.flag").exists()  # survives an agent restart
        assert toggle_kill(app) is False
        assert open_notepad(client)["ok"] and launcher.launched
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert audit.count('"via": "hotkey"') == 2
