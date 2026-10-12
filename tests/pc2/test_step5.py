"""App flows step 5 on PC2: OBS remote control (fake obs-websocket v5), Steam library files, Office copies."""
from __future__ import annotations

import base64
import hashlib
import json
import threading
from pathlib import Path

import pytest

from agent.tools import obs, office, steam
from voice_contracts.tools import NoArgs, ObsArgs, SteamLaunchArgs


def test_obs_auth_string_matches_the_protocol():
    secret = base64.b64encode(hashlib.sha256(b"pw" + b"salt").digest()).decode()
    expected = base64.b64encode(hashlib.sha256((secret + "chal").encode()).digest()).decode()
    assert obs.auth_string("pw", "salt", "chal") == expected


class FakeObs:
    """obs-websocket v5: Hello with auth challenge, Identify, then requests."""

    def __init__(self, password="pw"):
        from websockets.sync.server import serve
        self.password, self.state = password, {"rec": False, "stream": False, "scene": "Main"}
        self.requests: list[str] = []
        self.server = serve(self.handler, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def handler(self, ws):
        ws.send(json.dumps({"op": 0, "d": {"rpcVersion": 1, "authentication": {"salt": "s", "challenge": "c"}}}))
        ident = json.loads(ws.recv())
        if ident["d"].get("authentication") != obs.auth_string(self.password, "s", "c"):
            ws.close(4009, "Authentication failed")
            return
        ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        for raw in ws:
            d = json.loads(raw)["d"]
            t = d["requestType"]
            self.requests.append(t)
            data = {}
            if t == "GetRecordStatus":
                data = {"outputActive": self.state["rec"], "outputTimecode": "00:00:01"}
            elif t == "GetStreamStatus":
                data = {"outputActive": self.state["stream"], "outputTimecode": ""}
            elif t == "GetSceneList":
                data = {"currentProgramSceneName": self.state["scene"],
                        "scenes": [{"sceneName": "Gaming"}, {"sceneName": "Main"}]}
            elif t == "StartRecord":
                self.state["rec"] = True
            elif t == "StopRecord":
                self.state["rec"] = False
            elif t == "StartStream":
                self.state["stream"] = True
            elif t == "SetCurrentProgramScene":
                self.state["scene"] = d["requestData"]["sceneName"]
            ws.send(json.dumps({"op": 7, "d": {"requestType": t, "requestId": d["requestId"],
                                               "requestStatus": {"result": True, "code": 100},
                                               "responseData": data}}))

    def close(self):
        self.server.shutdown()


class Ctx:
    def __init__(self):
        self.sleep = lambda s: None
        self.launcher = type("L", (), {"is_running": staticmethod(lambda p: True)})()


@pytest.fixture
def fake_obs(monkeypatch):
    srv = FakeObs()
    monkeypatch.setattr(obs, "obs_config", lambda: {"server_enabled": True, "server_port": srv.port,
                                                     "server_password": "pw"})
    yield srv
    srv.close()


def test_obs_record_scene_and_stream(fake_obs):
    ctx = Ctx()
    r = obs.obs_control(ObsArgs(action="start_recording"), ctx)
    assert r.ok and r.verified and r.data["recording"] and "StartRecord" in fake_obs.requests
    r = obs.obs_control(ObsArgs(action="set_scene", scene="gaming"), ctx)
    assert r.ok and r.verified and r.data["scene"] == "Gaming"
    assert "no scene" in obs.obs_control(ObsArgs(action="set_scene", scene="Nope"), ctx).error
    r = obs.obs_start_stream(NoArgs(), ctx)
    assert r.ok and r.verified and r.data["streaming"]


def test_obs_wrong_password_is_reported(fake_obs, monkeypatch):
    monkeypatch.setattr(obs, "obs_config", lambda: {"server_enabled": True, "server_port": fake_obs.port,
                                                     "server_password": "wrong"})
    r = obs.obs_control(ObsArgs(action="status"), Ctx())
    assert not r.ok


def test_obs_remote_control_off_is_explained(tmp_path, monkeypatch):
    cfg = tmp_path / "obs-studio" / "plugin_config" / "obs-websocket"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text(json.dumps({"server_enabled": False}))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    with pytest.raises(obs.ObsError, match="WebSocket Server Settings"):
        obs.obs_config()


def test_steam_installed_games(tmp_path, monkeypatch):
    lib = tmp_path / "SteamLibrary"
    (tmp_path / "Steam" / "steamapps").mkdir(parents=True)
    (lib / "steamapps").mkdir(parents=True)
    def esc(x):  # VDF escapes backslashes
        return str(x).replace("\\", "\\\\")
    (tmp_path / "Steam" / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n "0" {{ "path" "{esc(tmp_path / "Steam")}" }}\n "1" {{ "path" "{esc(lib)}" }}\n}}')
    def acf(where, appid, name, flags, played):
        (where / "steamapps" / f"appmanifest_{appid}.acf").write_text(
            f'"AppState"\n{{\n "appid" "{appid}"\n "name" "{name}"\n "StateFlags" "{flags}"\n'
            f' "LastPlayed" "{played}"\n}}')
    acf(tmp_path / "Steam", "228980", "Steamworks Common Redistributables", 4, 0)
    acf(lib, "570", "Dota 2", 4, 100)
    acf(lib, "730", "Counter-Strike 2", 4, 200)
    acf(lib, "4704690", "Still downloading", 1026, 0)
    games = steam.installed_games(tmp_path / "Steam")
    assert [g["name"] for g in games] == ["Counter-Strike 2", "Dota 2"]

    launched = []
    monkeypatch.setattr(steam, "installed_games", lambda: games)
    ctx = type("C", (), {"launcher": type("L", (), {"open_uri": staticmethod(launched.append)})()})()
    assert steam.steam_launch(SteamLaunchArgs(appid="570"), ctx).ok and launched == ["steam://rungameid/570"]
    assert not steam.steam_launch(SteamLaunchArgs(appid="999"), ctx).ok


def test_office_copy_never_overwrites(tmp_path):
    f = tmp_path / "Report.docx"
    f.write_text("x")
    first = office._copy_path(str(f))
    assert first.name == "Report (voice copy).docx"
    first.write_text("x")
    assert office._copy_path(str(f)).name == "Report (voice copy 2).docx"


def test_office_mru_line_format():
    m = office._MRU_ITEM.search("[F00000000][T01DD1613C41E1B40][O00000000]*C:\\Users\\me\\Docs\\Plan.docx")
    assert m and Path(m["path"]).name == "Plan.docx"
