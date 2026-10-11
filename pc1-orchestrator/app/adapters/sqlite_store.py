"""SQLite store (WAL): jobs, events (§21.3), audit log with hash chain (TC-S10), device tokens."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, created_at REAL, updated_at REAL, state TEXT, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created_at DESC);
CREATE TABLE IF NOT EXISTS events (
  ts TEXT, job_id TEXT, stage TEXT, status TEXT, duration_ms INTEGER, model TEXT,
  tokens_in INTEGER, tokens_out INTEGER, tool TEXT, risk INTEGER, outcome TEXT, error_code TEXT);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, job_id TEXT, data TEXT,
  prev_hash TEXT, hash TEXT);
CREATE TABLE IF NOT EXISTS devices (
  name TEXT PRIMARY KEY, token_hash TEXT UNIQUE, created_at REAL, revoked_at REAL);
"""
GENESIS = "0" * 64


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _audit_hash(prev: str, ts: float, kind: str, job_id: str | None, data: str) -> str:
    return hashlib.sha256(f"{prev}|{ts!r}|{kind}|{job_id or ''}|{data}".encode()).hexdigest()


class SqliteStore:
    def __init__(self, path: str | Path = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    # -- jobs
    def save_job(self, job: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO jobs(id, created_at, updated_at, state, data) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, "
                "state=excluded.state, data=excluded.data",
                (job["id"], job["created_at"], job["updated_at"], job["state"],
                 json.dumps(job, ensure_ascii=False)))

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?",
                                    (max(1, min(limit, 200)),)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    # -- events / metrics
    def add_event(self, job_id: str, stage: str, status: str, duration_ms: int, **extra: Any) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO events(ts, job_id, stage, status, duration_ms, model, tokens_in, "
                "tokens_out, tool, risk, outcome, error_code) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.strftime("%Y-%m-%dT%H:%M:%S%z"), job_id, stage, status, duration_ms,
                 extra.get("model"), extra.get("tokens_in"), extra.get("tokens_out"),
                 extra.get("tool"), extra.get("risk"), extra.get("outcome"), extra.get("error_code")))

    def events(self, job_id: str | None = None) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM events", ()
        if job_id:
            q, args = q + " WHERE job_id=?", (job_id,)
        with self._lock:
            return [dict(r) for r in self._db.execute(q, args).fetchall()]

    # -- audit (append-only, hash chained)
    def append_audit(self, kind: str, job_id: str | None, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock:
            row = self._db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row["hash"] if row else GENESIS
            ts = time.time()
            h = _audit_hash(prev, ts, kind, job_id, payload)
            self._db.execute("INSERT INTO audit(ts, kind, job_id, data, prev_hash, hash) "
                             "VALUES(?,?,?,?,?,?)", (ts, kind, job_id, payload, prev, h))

    def audit_rows(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM audit ORDER BY seq").fetchall()]

    def verify_audit(self) -> bool:
        prev = GENESIS
        for r in self.audit_rows():
            if r["prev_hash"] != prev or r["hash"] != _audit_hash(prev, r["ts"], r["kind"],
                                                                 r["job_id"], r["data"]):
                return False
            prev = r["hash"]
        return True

    # -- devices (US-803)
    def create_device(self, name: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._db.execute(
                "INSERT INTO devices(name, token_hash, created_at, revoked_at) VALUES(?,?,?,NULL) "
                "ON CONFLICT(name) DO UPDATE SET token_hash=excluded.token_hash, "
                "created_at=excluded.created_at, revoked_at=NULL",
                (name, _hash_token(token), time.time()))
        return token

    def revoke_device(self, name: str) -> bool:
        with self._lock:
            cur = self._db.execute("UPDATE devices SET revoked_at=? WHERE name=? AND revoked_at IS NULL",
                                   (time.time(), name))
        return cur.rowcount > 0

    def check_token(self, token: str) -> str | None:
        if not token or len(token) > 256:
            return None
        with self._lock:
            row = self._db.execute("SELECT name FROM devices WHERE token_hash=? AND revoked_at IS NULL",
                                   (_hash_token(token),)).fetchone()
        return row["name"] if row else None

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT name, created_at, revoked_at FROM devices ORDER BY name").fetchall()]
