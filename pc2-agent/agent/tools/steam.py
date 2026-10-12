"""Steam games (app flows step 5): installed games from Steam's own library files, launched through Steam."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from voice_contracts.models import ToolResult
from voice_contracts.tools import SteamLaunchArgs

from . import ToolContext, register

STEAM = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam"
_KV = re.compile(r'"(?P<k>[^"]+)"\s+"(?P<v>[^"]*)"')
_TOOLS = {"228980"}  # Steamworks Common Redistributables: not a game
_cache: dict[str, Any] = {"at": 0.0, "games": []}


def _libraries(steam: Path) -> list[Path]:
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    libs = [steam]
    if vdf.exists():
        for m in _KV.finditer(vdf.read_text(encoding="utf-8", errors="replace")):
            if m["k"] == "path":
                p = Path(m["v"].replace("\\\\", "\\"))
                if p not in libs:
                    libs.append(p)
    return libs


def installed_games(steam: Path = STEAM) -> list[dict[str, str]]:
    """Fully installed games, most recently played first (cached for a minute)."""
    if time.time() - _cache["at"] < 60 and steam == STEAM:
        return list(_cache["games"])
    games = []
    for lib in _libraries(steam):
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            kv = {m["k"]: m["v"] for m in _KV.finditer(acf.read_text(encoding="utf-8", errors="replace"))}
            appid = kv.get("appid", "")
            fully = (int(kv.get("StateFlags", "0") or 0) & 4) == 4  # 4 = fully installed
            if appid and appid not in _TOOLS and fully and "Redistributable" not in kv.get("name", ""):
                games.append({"appid": appid, "name": kv.get("name", appid)[:80],
                              "last_played": kv.get("LastPlayed", "0")})
    games.sort(key=lambda g: int(g["last_played"] or 0), reverse=True)
    if steam == STEAM:
        _cache.update(at=time.time(), games=games)
    return games


@register("steam_launch")
def steam_launch(args: SteamLaunchArgs, ctx: ToolContext) -> ToolResult:
    game = next((g for g in installed_games() if g["appid"] == args.appid), None)
    if game is None:
        return ToolResult(ok=False, error="that game is not installed in Steam on the PC")
    ctx.launcher.open_uri(f"steam://rungameid/{args.appid}")  # Steam starts the game (no shell)
    return ToolResult(ok=True, verified=True, data={"game": game["name"], "appid": args.appid})
