"""SQLite store: every sub-task run, every disagreement, every correction, the gate's state."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, ts REAL, scenario_id TEXT, session_id TEXT, split TEXT, policy_version TEXT,
  subtask TEXT, lane TEXT, phase TEXT, output TEXT, passed INTEGER, wrong TEXT, tokens_in INTEGER,
  tokens_out INTEGER, latency_ms REAL, request_id TEXT, record TEXT, kept INTEGER, served INTEGER, tags TEXT);
CREATE TABLE IF NOT EXISTS disagreements (
  id INTEGER PRIMARY KEY, ts REAL, scenario_id TEXT, subtask TEXT, policy_version TEXT, teacher TEXT,
  shadow TEXT, truth TEXT, teacher_ok INTEGER, shadow_ok INTEGER, who_right TEXT, tags TEXT);
CREATE TABLE IF NOT EXISTS corrections (
  id INTEGER PRIMARY KEY, ts REAL, scenario_id TEXT, subtask TEXT, policy_version TEXT, bad TEXT,
  fixed TEXT, attempts INTEGER, status TEXT, request_id TEXT, tags TEXT, note TEXT, request TEXT,
  source TEXT);
CREATE TABLE IF NOT EXISTS gate (
  subtask TEXT PRIMARY KEY, state TEXT, version TEXT, policy_version TEXT, since REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS gate_events (
  id INTEGER PRIMARY KEY, ts REAL, subtask TEXT, old TEXT, new TEXT, version TEXT, reason TEXT);
"""


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by FastAPI's worker threads, so every use goes through a lock.
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for col in ("note", "request", "source"):  # older databases: add the correction columns
            try:
                self.db.execute(f"ALTER TABLE corrections ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
        self.db.commit()

    def insert(self, table: str, **row) -> int:
        row = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()}
        row.setdefault("ts", time.time())
        cols = ",".join(row)
        q = ",".join("?" * len(row))
        with self.lock:
            cur = self.db.execute(f"INSERT INTO {table} ({cols}) VALUES ({q})", list(row.values()))
            self.db.commit()
            return cur.lastrowid

    def query(self, sql: str, *args) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def execute(self, sql: str, *args) -> int:
        """Write statement (UPDATE/DELETE/INSERT OR ...). Returns the row count."""
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.rowcount

    def gate_state(self, subtask: str) -> dict:
        rows = self.query("SELECT * FROM gate WHERE subtask=?", subtask)
        return rows[0] if rows else {"subtask": subtask, "state": "shadow", "version": None, "policy_version": None}

    def set_gate(self, subtask: str, state: str, version: str | None, policy_version: str | None, reason: str):
        with self.lock:
            old = self.gate_state(subtask)["state"]
            self.db.execute("INSERT OR REPLACE INTO gate VALUES (?,?,?,?,?,?)",
                            (subtask, state, version, policy_version, time.time(), reason))
            self.db.commit()
            self.insert("gate_events", subtask=subtask, old=old, new=state, version=version, reason=reason)

    def update(self, table: str, row_id: int, **row) -> None:
        row = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()}
        sets = ",".join(f"{k}=?" for k in row)
        with self.lock:
            self.db.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*row.values(), row_id])
            self.db.commit()
