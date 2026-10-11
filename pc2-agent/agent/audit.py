"""Local append-only audit log on PC2 (JSONL, hash chained) — §10.3, T9."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._prev = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = GENESIS
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)["hash"]
        return last

    def append(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            rec = {"ts": time.time(), "kind": kind, "data": data, "prev": self._prev}
            body = json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str)
            rec["hash"] = hashlib.sha256(body.encode()).hexdigest()
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            self._prev = rec["hash"]

    def verify(self) -> bool:
        prev = GENESIS
        if not self.path.exists():
            return True
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                h = rec.pop("hash")
                body = json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str)
                if rec["prev"] != prev or hashlib.sha256(body.encode()).hexdigest() != h:
                    return False
                prev = h
        return True
