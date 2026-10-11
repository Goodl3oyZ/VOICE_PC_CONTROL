"""Local kill switch — works even when the network or PC1 is down (§10.3, US-607 partial).

  python -m agent.killswitch on      # agent refuses every action except status/stop
  python -m agent.killswitch off
  python -m agent.killswitch status

A tray icon / global hotkey that calls this is planned for Sprint 10.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .config import AgentConfig
from .policy import KillSwitch


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    cfg_path = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "agent_config.json"
    ks = KillSwitch(Path(AgentConfig.load(cfg_path).data_dir) / "killswitch.flag")
    if cmd == "on":
        ks.set(True)
    elif cmd == "off":
        ks.set(False)
    elif cmd != "status":
        print("usage: python -m agent.killswitch on|off|status [config]", file=sys.stderr)
        return 2
    print("kill switch:", "ON" if ks.on else "off")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
