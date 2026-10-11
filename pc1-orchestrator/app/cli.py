"""Admin CLI (US-803): register / revoke phone tokens, verify the audit chain.

  python -m app.cli add-device phone1      # prints the token once — store it in the PWA
  python -m app.cli revoke-device phone1
  python -m app.cli list-devices
  python -m app.cli verify-audit
  python -m app.cli export-audit [--since 2026-10-01] [--format csv] [-o file]   # US-704
  python -m app.cli set-pairing-key          # new Secret Key for pairing browsers (printed once)
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
    sub.add_parser("set-pairing-key")
    ex = sub.add_parser("export-audit")
    ex.add_argument("--since", help="YYYY-MM-DD (local time)")
    ex.add_argument("--format", choices=["jsonl", "csv"], default="jsonl")
    ex.add_argument("-o", "--output", help="file (default: stdout)")
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
    elif a.cmd == "set-pairing-key":
        from .api.webauth import PAIRING_KEY_SETTING, hash_key, new_pairing_key
        key = new_pairing_key()
        store.set_setting(PAIRING_KEY_SETTING, hash_key(key))
        print(key)
        print("(shown once; old key no longer works for NEW devices, paired devices stay paired)", file=sys.stderr)
    elif a.cmd == "export-audit":
        import time

        from .core.audit_export import export_audit
        since = time.mktime(time.strptime(a.since, "%Y-%m-%d")) if a.since else None
        text = export_audit(store.audit_rows(), store.verify_audit(), since, a.format)
        if a.output:
            with open(a.output, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            print(f"wrote {a.output}", file=sys.stderr)
        else:
            try:
                sys.stdout.write(text)
                sys.stdout.flush()
            except BrokenPipeError:  # piped into `head`: fine, stop quietly
                import os
                os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    elif a.cmd == "verify-audit":
        ok = store.verify_audit()
        print("audit chain OK" if ok else "AUDIT CHAIN BROKEN")
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
