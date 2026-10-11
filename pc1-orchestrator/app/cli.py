"""Admin CLI (US-803): register / revoke phone tokens, verify the audit chain.

  python -m app.cli add-device phone1      # prints the token once — store it in the PWA
  python -m app.cli revoke-device phone1
  python -m app.cli list-devices
  python -m app.cli verify-audit
"""
from __future__ import annotations

import argparse
import sys

from .adapters.sqlite_store import SqliteStore
from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vpc")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("add-device").add_argument("name")
    sub.add_parser("revoke-device").add_argument("name")
    sub.add_parser("list-devices")
    sub.add_parser("verify-audit")
    a = p.parse_args(argv)
    store = SqliteStore(Settings().db_path)

    if a.cmd == "add-device":
        print(store.create_device(a.name))
    elif a.cmd == "revoke-device":
        if not store.revoke_device(a.name):
            print("no active device with that name", file=sys.stderr)
            return 1
        print("revoked")
    elif a.cmd == "list-devices":
        for d in store.list_devices():
            print(f"{d['name']}\t{'revoked' if d['revoked_at'] else 'active'}")
    elif a.cmd == "verify-audit":
        ok = store.verify_audit()
        print("audit chain OK" if ok else "AUDIT CHAIN BROKEN")
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
