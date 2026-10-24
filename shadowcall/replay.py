"""Replay mode: fill the console from the real live run, offline, with no keys and no model calls.

`export()` turns the live run's SQLite file (gitignored) into a committed, key-free JSON file.
`load()` writes that file into the app's store, derives disagreements from the real held-out
replies and lets the real gate rule decide each job from the real held-out scores."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import gate, synth
from .config import ROOT, Settings
from .store import Store
from .subtasks import SUBTASKS, truth_output

REPLAY_FILE = ROOT / "data" / "live_replay.json"
LONDON = ZoneInfo("Europe/London")
PHASE_MAP = {"eval_base": "eval"}  # the pre-registered held-out set is the gate's "eval" phase
RUN_COLS = ["id", "ts", "scenario_id", "session_id", "split", "policy_version", "subtask", "lane", "phase", "output",
            "passed", "wrong", "tokens_in", "tokens_out", "latency_ms", "request_id", "record", "kept", "served", "tags"]
COR_COLS = ["id", "ts", "scenario_id", "subtask", "policy_version", "bad", "fixed", "attempts", "status", "request_id",
            "tags", "note", "request", "source"]
SECRET = re.compile(r"(?i)(authorization|bearer\s+[a-z0-9]|api[_-]?key\s*[:=]|x-api-key|sk-[A-Za-z0-9]{16}|mbt_[A-Za-z0-9]{12}|xi-api-key)")


def file_path() -> Path:
    return Path(os.environ.get("SHADOWCALL_REPLAY_FILE", str(REPLAY_FILE)))


def bst(ts: float) -> str:
    return datetime.fromtimestamp(ts, LONDON).strftime("%d %b, %H:%M %Z").lstrip("0")


def check_clean(text: str, keys: list[str]) -> None:
    for k in keys:
        if k and k in text:
            raise ValueError("a key value is in the replay file")
    m = SECRET.search(text)
    if m:
        raise ValueError(f"secret-like text in the replay file: {m.group(0)[:12]}…")


def export(db_path: str, card_files: list[str], out: Path, live_results: Path | None = None) -> dict:
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    runs = [dict(r) for r in db.execute(f"SELECT {','.join(RUN_COLS)} FROM runs ORDER BY id")]
    cors = [dict(r) for r in db.execute(f"SELECT {','.join(COR_COLS)} FROM corrections ORDER BY id")]
    assert not [r for r in runs if r["split"] == "heldout" and (r["kept"] or r["record"] == "full")], "held-out leak"
    ids = {r["scenario_id"] for r in runs}
    cards = {}
    for f in card_files:
        for c in synth.load(f):
            if c.id in ids:
                cards[c.id] = c.to_dict()
    missing = ids - set(cards)
    assert not missing, f"no card for {sorted(missing)[:3]}"
    ts = [r["ts"] for r in runs]
    ev = [r["ts"] for r in runs if r["phase"].startswith("eval")]
    data = {
        "what": "Real ShadowCall live run through Mubit (frontier gpt-6-sol, small openai/gpt-oss-20b). "
                "Replies, scores, tokens, latency and Mubit request ids as recorded. No keys or request headers.",
        "window": {"from": min(ts), "to": max(ts), "eval_to": max(ev) if ev else max(ts)},
        "runs": runs, "corrections": cors, "cards": cards,
        "live_results": json.loads(live_results.read_text(encoding="utf-8")) if live_results and live_results.exists() else None,
    }
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    check_clean(text, [os.environ.get(k, "") for k in ("MUBIT_API_KEY", "MUBIT_API_KEY_RAW", "ELEVENLABS_API_KEY")])
    out.write_text(text, encoding="utf-8")
    return {"runs": len(runs), "corrections": len(cors), "cards": len(cards), "bytes": len(text)}


def read(path: Path | None = None) -> dict:
    return json.loads((path or file_path()).read_text(encoding="utf-8"))


def load(store: Store, s: Settings, data: dict) -> dict:
    """Replace the store's call data with the replay. Accounts and sessions are left alone."""
    with store.lock:
        for t in ("runs", "corrections", "disagreements", "gate", "gate_events", "cards"):
            store.db.execute(f"DELETE FROM {t}")
        store.db.executemany(f"INSERT INTO runs ({','.join(RUN_COLS)}) VALUES ({','.join('?' * len(RUN_COLS))})",
                             [[PHASE_MAP.get(r[c], r[c]) if c == "phase" else r[c] for c in RUN_COLS] for r in data["runs"]])
        store.db.executemany(f"INSERT INTO corrections ({','.join(COR_COLS)}) VALUES ({','.join('?' * len(COR_COLS))})",
                             [[r.get(c) for c in COR_COLS] for r in data["corrections"]])
        store.db.executemany("INSERT INTO cards (id, body) VALUES (?, ?)",
                             [(k, json.dumps(v)) for k, v in data["cards"].items()])
        store.db.commit()
    cards = {k: synth.Scenario(**v) for k, v in data["cards"].items()}
    n_dis = _disagreements(store, cards)
    decisions = {}
    when = data["window"]["eval_to"]
    for t in SUBTASKS:
        d = gate.evaluate(store, s, t, "v1", "shadow")
        store.set_gate(t, "switched" if d.promote else "shadow", "shadow-v1-live" if d.promote else None, "v1", d.reason)
        decisions[t] = {"promote": d.promote, "reason": d.reason, "n": d.n}
    with store.lock:  # date the decisions to when the real test finished, not to server start
        store.db.execute("UPDATE gate SET since=?", (when,))
        store.db.execute("UPDATE gate_events SET ts=?", (when,))
        store.db.commit()
    return {"runs": len(data["runs"]), "corrections": len(data["corrections"]), "disagreements": n_dis, "gate": decisions}


def _disagreements(store: Store, cards: dict) -> int:
    rows = store.query("SELECT * FROM runs WHERE phase LIKE 'eval%' ORDER BY id")
    pair: dict = {}
    for r in rows:
        pair.setdefault((r["scenario_id"], r["subtask"], r["phase"]), {})[r["lane"]] = r
    n = 0
    for (sid, st, _), lanes in pair.items():
        t, sh = lanes.get("teacher"), lanes.get("shadow")
        if not t or not sh or t["passed"] == sh["passed"]:
            continue
        try:
            truth = truth_output(st, cards[sid], None)
        except Exception:
            truth = None
        store.insert("disagreements", ts=sh["ts"], scenario_id=sid, subtask=st, policy_version=t["policy_version"],
                     teacher=t["output"], shadow=sh["output"], truth=json.dumps(truth) if truth is not None else None,
                     teacher_ok=t["passed"], shadow_ok=sh["passed"], who_right="teacher" if t["passed"] else "shadow",
                     tags=t["tags"])
        n += 1
    return n


def label(data: dict) -> str:
    w = data["window"]
    a = datetime.fromtimestamp(w["from"], LONDON)
    b = datetime.fromtimestamp(w["eval_to"], LONDON)
    return f"Replaying real Mubit calls from {a.day} {a:%b}, {a:%H:%M}–{b:%H:%M} {b:%Z} — no new API calls"


class Clock:
    """The live feed in replay mode: real calls reappear in their real order, sped up, on a loop."""

    def __init__(self, store: Store, speed: float = 30.0, now=time.time):
        self.store, self.speed, self.now, self.start = store, speed, now, now()
        r = store.query("SELECT MIN(ts) a, MAX(ts) b FROM runs")[0]
        self.t0, self.t1 = r["a"] or 0.0, r["b"] or 0.0

    def position(self) -> tuple[int, float]:
        span = max(self.t1 - self.t0, 1.0)
        el = (self.now() - self.start) * self.speed
        return int(el // span), self.t0 + el % span
