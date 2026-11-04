"""SQLite storage for cases, files, and jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    params      TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    stage      TEXT NOT NULL,
    backend    TEXT DEFAULT 'native',
    status     TEXT DEFAULT 'queued',   -- queued|running|done|failed|canceled
    created_at REAL NOT NULL,
    started_at REAL,
    ended_at   REAL,
    returncode INTEGER,
    log_path   TEXT,
    details    TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS artifacts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id   INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind      TEXT NOT NULL,           -- input | output | report
    rel_path  TEXT NOT NULL,
    size      INTEGER DEFAULT 0,
    added_at  REAL NOT NULL,
    UNIQUE(case_id, kind, rel_path)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------- helpers --
    def _exec(self, sql, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _query(self, sql, args=()):
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # ---------------------------------------------------------------- cases --
    def create_case(self, name: str, description: str = "",
                    params: dict | None = None) -> int:
        now = time.time()
        cur = self._exec(
            "INSERT INTO cases (name, description, created_at, updated_at, params)"
            " VALUES (?,?,?,?,?)",
            (name, description, now, now, json.dumps(params or {})))
        return cur.lastrowid

    def update_case(self, case_id: int, **fields) -> None:
        allowed = {"name", "description", "params"}
        sets, args = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=?")
            args.append(json.dumps(v) if k == "params" else v)
        sets.append("updated_at=?")
        args.append(time.time())
        args.append(case_id)
        self._exec(f"UPDATE cases SET {', '.join(sets)} WHERE id=?", args)

    def delete_case(self, case_id: int) -> None:
        self._exec("DELETE FROM cases WHERE id=?", (case_id,))

    def get_case(self, case_id: int):
        rows = self._query("SELECT * FROM cases WHERE id=?", (case_id,))
        row = rows[0] if rows else None
        if row:
            row = dict(row)
            row["params"] = json.loads(row["params"] or "{}")
        return row

    def list_cases(self):
        rows = [dict(r) for r in self._query(
            "SELECT * FROM cases ORDER BY created_at DESC")]
        for r in rows:
            r["params"] = json.loads(r["params"] or "{}")
        return rows

    # ----------------------------------------------------------------- jobs --
    def create_job(self, case_id: int, stage: str, backend: str = "native",
                   details: dict | None = None) -> int:
        cur = self._exec(
            "INSERT INTO jobs (case_id, stage, backend, status, created_at, details)"
            " VALUES (?,?,?,?,?,?)",
            (case_id, stage, backend, "queued", time.time(),
             json.dumps(details or {})))
        return cur.lastrowid

    def update_job(self, job_id: int, **fields) -> None:
        allowed = {"status", "started_at", "ended_at", "returncode",
                   "log_path", "details", "backend"}
        sets, args = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=?")
            args.append(json.dumps(v) if k == "details" else v)
        args.append(job_id)
        self._exec(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", args)

    def get_job(self, job_id: int):
        rows = self._query("SELECT * FROM jobs WHERE id=?", (job_id,))
        row = dict(rows[0]) if rows else None
        if row:
            row["details"] = json.loads(row["details"] or "{}")
        return row

    def list_jobs(self, case_id: int | None = None, limit: int = 100):
        if case_id is None:
            rows = self._query(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
        else:
            rows = self._query(
                "SELECT * FROM jobs WHERE case_id=? ORDER BY id DESC LIMIT ?",
                (case_id, limit))
        out = []
        for r in rows:
            r = dict(r)
            r["details"] = json.loads(r["details"] or "{}")
            out.append(r)
        return out

    def running_jobs(self):
        return self._query("SELECT id FROM jobs WHERE status='running'")

    # ------------------------------------------------------------ artifacts --
    def add_artifact(self, case_id: int, kind: str, rel_path: str,
                     size: int = 0) -> None:
        self._exec(
            "INSERT OR REPLACE INTO artifacts (case_id, kind, rel_path, size, added_at)"
            " VALUES (?,?,?,?,?)",
            (case_id, kind, rel_path, size, time.time()))

    def remove_artifact(self, case_id: int, kind: str, rel_path: str) -> None:
        self._exec("DELETE FROM artifacts WHERE case_id=? AND kind=? AND rel_path=?",
                   (case_id, kind, rel_path))

    def list_artifacts(self, case_id: int, kind: str | None = None):
        if kind:
            rows = self._query(
                "SELECT * FROM artifacts WHERE case_id=? AND kind=?"
                " ORDER BY rel_path", (case_id, kind))
        else:
            rows = self._query(
                "SELECT * FROM artifacts WHERE case_id=? ORDER BY rel_path",
                (case_id,))
        return [dict(r) for r in rows]
