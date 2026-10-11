"""Run the agent in the logged-in user session (not a Windows Service — UI automation needs the desktop).

  set VPC_PC2_SECRET=...   (same value as on PC1; or store it with `python -m agent.secret set`)
  python -m agent.main [path\\to\\agent_config.json]
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import time
from pathlib import Path

import uvicorn

from .config import AgentConfig
from .hotkey import start_hotkey_thread
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


def wait_for_address(host: str, port: int, timeout_s: float = 300) -> None:
    """At logon the VPN (Tailscale) may come up after us: wait until the bind address exists."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
            return
        except OSError as e:
            if time.monotonic() > deadline:
                raise SystemExit(f"cannot bind {host}:{port}: {e}") from e
            logging.info("waiting for %s to become available (%s)", host, e)
            time.sleep(5)


def main() -> None:
    here = Path(__file__).resolve().parent.parent
    default = here / "agent_config.local.json"  # machine-specific, gitignored
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (default if default.exists() else here / "agent_config.json")
    cfg = AgentConfig.load(cfg_path)
    if sys.stderr is None:  # pythonw (Task Scheduler): no console, log to a file instead
        Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(Path(cfg.data_dir) / "agent.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    secret = load_secret()
    if cfg.pc1_ws_url:  # outbound mode: no listening socket at all
        import asyncio

        from .connector import run_connector
        cfg.allowed_clients = ["127.0.0.1"]  # relayed requests enter in-process from the connector only
        app = create_app(cfg, secret, WindowsLauncher())
        start_hotkey_thread(app, cfg.killswitch_hotkey)
        asyncio.run(run_connector(app, cfg.pc1_ws_url, secret))
        return
    wait_for_address(cfg.bind_host, cfg.port)
    app = create_app(cfg, secret, WindowsLauncher())
    start_hotkey_thread(app, cfg.killswitch_hotkey)
    uvicorn.run(app, host=cfg.bind_host, port=cfg.port, ssl_certfile=cfg.tls_certfile,
                ssl_keyfile=cfg.tls_keyfile, log_level="info")


if __name__ == "__main__":
    main()
