"""Print the pairing token for the Voice PC Chrome extension (paste it into the extension's options page).

  python -m agent.ext_token [path\to\agent_config.json]
"""
from __future__ import annotations

import sys
from pathlib import Path

from .config import AgentConfig
from .extension import load_token


def main() -> None:
    here = Path(__file__).resolve().parent.parent
    default = here / "agent_config.local.json"
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else (default if default.exists() else here / "agent_config.json")
    print(load_token(Path(AgentConfig.load(path).data_dir)))  # the owner's own terminal on PC2


if __name__ == "__main__":
    main()
