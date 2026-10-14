"""Data for the public demo page (/demo): the real flow screens and command guide, built from the repo's
generic knowledge file and a made-up PC. Nothing here comes from the owner's PC or database.

    python -m app.demo_data      (from pc1-orchestrator; tests fail when the file is out of date)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core.capabilities import capabilities
from .core.flows import public_flows
from .core.knowledge import Knowledge

KNOWLEDGE = Path(__file__).resolve().parents[1] / "data" / "knowledge.json"
OUT = Path(__file__).resolve().parents[2] / "mobile-pwa" / "src" / "demo" / "data.json"

FAKE_PC: dict[str, Any] = {
    "found_projects": [{"name": "my-website", "label": "my-website"}],
    "office_recent": {
        "word": [{"name": "Trip plan.docx", "path": "C:\\Users\\you\\Documents\\Trip plan.docx"}],
        "excel": [{"name": "Budget.xlsx", "path": "C:\\Users\\you\\Documents\\Budget.xlsx"}],
        "powerpoint": [],
    },
    "steam_games": [{"appid": "570", "name": "Dota 2"}],
}


def render() -> str:
    return json.dumps(demo_data(), ensure_ascii=False, indent=1) + "\n"


def demo_data() -> dict[str, Any]:
    kb = Knowledge.load(str(KNOWLEDGE))
    return {"flows": public_flows(kb, lambda _key: None, FAKE_PC), "capabilities": capabilities(kb, "en")}


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
