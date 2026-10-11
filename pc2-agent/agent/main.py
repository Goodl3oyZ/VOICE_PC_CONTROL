"""Run the agent in the logged-in user session (not a Windows Service — UI automation needs the desktop).

  set VPC_PC2_SECRET=...   (same value as on PC1; or store it with `python -m agent.secret set`)
  python -m agent.main [path\\to\\agent_config.json]
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import uvicorn

from .config import AgentConfig
from .launcher import WindowsLauncher
from .server import create_app

KEYRING_SERVICE = "voice-pc-control"


def load_secret() -> bytes:
    secret = os.environ.get("VPC_PC2_SECRET", "")
    if not secret:
        try:
            import keyring  # Windows Credential Manager (DPAPI), §20.6

            secret = keyring.get_password(KEYRING_SERVICE, "pc2_secret") or ""
        except ImportError:
            pass
    if len(secret) < 32:
        raise SystemExit("Set VPC_PC2_SECRET (>= 32 chars) or store it in Credential Manager via keyring")
    return secret.encode()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "agent_config.json"
    cfg = AgentConfig.load(cfg_path)
    app = create_app(cfg, load_secret(), WindowsLauncher())
    uvicorn.run(app, host=cfg.bind_host, port=cfg.port, ssl_certfile=cfg.tls_certfile,
                ssl_keyfile=cfg.tls_keyfile, log_level="info")


if __name__ == "__main__":
    main()
