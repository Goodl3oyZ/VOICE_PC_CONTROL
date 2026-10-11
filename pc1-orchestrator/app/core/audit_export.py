"""Audit export (US-704): the hash-chained audit log as JSONL or CSV, with a verification trailer.

The chain is verified over the WHOLE log (a filtered export can't prove anything on its own); the trailer
records the result and the last hash so a saved export can later be compared with the live log.
"""
from __future__ import annotations

import csv
import io
import json
import time
from typing import Any


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))


def export_audit(rows: list[dict[str, Any]], chain_ok: bool, since: float | None = None,
                 fmt: str = "jsonl") -> str:
    selected = [r for r in rows if since is None or r["ts"] >= since]
    trailer = {"export": {"rows": len(selected), "total_rows": len(rows), "chain_ok": chain_ok,
                          "last_hash": rows[-1]["hash"] if rows else None, "exported_at": _iso(time.time()),
                          "since": _iso(since) if since else None}}
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["seq", "time", "kind", "job_id", "tool", "state", "data", "hash"])
        for r in selected:
            data = json.loads(r["data"])
            w.writerow([r["seq"], _iso(r["ts"]), r["kind"], r["job_id"] or "", data.get("tool", ""),
                        data.get("to", data.get("state", "")), r["data"], r["hash"]])
        w.writerow(["#", json.dumps(trailer)])
        return buf.getvalue()
    if fmt != "jsonl":
        raise ValueError("format must be jsonl or csv")
    lines = [json.dumps({"seq": r["seq"], "time": _iso(r["ts"]), "ts": r["ts"], "kind": r["kind"],
                         "job_id": r["job_id"], "data": json.loads(r["data"]), "prev_hash": r["prev_hash"],
                         "hash": r["hash"]}, ensure_ascii=False) for r in selected]
    lines.append(json.dumps(trailer))
    return "\n".join(lines) + "\n"
