"""Soak test (Gate G4): harmless commands through the real PC1 -> relay -> PC2 path for hours.

Runs ON PC1 as the service user. Creates a temporary paired device, revoked at the end. Each round runs
read-only commands and records success, latency, and the orchestrator's memory (to spot leaks).

  sudo -E -u vpc env PYTHONPATH=contracts:pc1-orchestrator .venv/bin/python eval/soak.py --hours 8
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
from pathlib import Path

import httpx

from app.adapters.sqlite_store import SqliteStore
from app.api.webauth import DEVICE_COOKIE, SESSION_COOKIE, Signer

COMMANDS = ["Status", "What tabs are open?", "git status of demo"]
DEVICE = "soak-test"


def service_rss_mb() -> float | None:
    try:
        pid = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", "voice-pc-control"],
                             capture_output=True, text=True).stdout.strip()
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except (OSError, ValueError):
        pass
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8)
    ap.add_argument("--every", type=float, default=300, help="seconds between rounds")
    ap.add_argument("--out", default="/var/lib/vpc/soak.jsonl")
    a = ap.parse_args()
    store = SqliteStore(os.environ["VPC_DB"])
    email = os.environ["VPC_ALLOWED_EMAILS"].split(",")[0].strip()
    signer = Signer(os.environ["VPC_SESSION_SECRET"].encode())
    device = store.create_device(DEVICE)
    out = open(a.out, "a", encoding="utf-8")  # noqa: SIM115
    end = time.time() + a.hours * 3600
    rounds = fails = 0
    lat: list[float] = []
    try:
        while time.time() < end:
            session = signer.dumps({"email": email, "exp": time.time() + 600})
            c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=60,
                             cookies={SESSION_COOKIE: session, DEVICE_COOKIE: device},
                             headers={"X-Requested-With": "voicepc", "Origin": os.environ["VPC_PUBLIC_URL"]})
            for text in COMMANDS:
                t0 = time.time()
                try:
                    jid = c.post("/command", json={"text": text}).json()["id"]
                    while True:
                        j = c.get(f"/jobs/{jid}").json()
                        if j["state"] in ("done", "failed", "cancelled", "clarifying") or time.time() - t0 > 90:
                            break
                        time.sleep(0.5)
                    ok = j["state"] == "done"
                    err = None if ok else (j.get("error") or j["state"])
                except (httpx.HTTPError, KeyError, ValueError) as e:
                    ok, err = False, f"{type(e).__name__}: {e}"
                dt = time.time() - t0
                rounds += 1
                fails += not ok
                lat.append(dt)
                out.write(json.dumps({"t": time.time(), "cmd": text, "ok": ok, "secs": round(dt, 2), "err": err,
                                      "rss_mb": service_rss_mb()}) + "\n")
                out.flush()
            c.close()
            time.sleep(a.every)
    finally:
        store.revoke_device(DEVICE)
        summary = {"commands": rounds, "failed": fails,
                   "success_rate": round((rounds - fails) / max(1, rounds), 4),
                   "p50_s": round(statistics.median(lat), 2) if lat else None,
                   "p95_s": round(sorted(lat)[int(len(lat) * 0.95) - 1], 2) if len(lat) >= 20 else None}
        out.write(json.dumps({"summary": summary}) + "\n")
        out.close()
        print(json.dumps(summary))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
