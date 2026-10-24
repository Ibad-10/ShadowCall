"""Live smoke run: ~10 cards end to end through Mubit. Separate DB (data/smoke.db). Never prints keys."""
import json, os, sys, time, traceback
from shadowcall.config import get_settings
from shadowcall.store import Store
from shadowcall import synth, evalh
from shadowcall.verify import make_claim_checker

s = get_settings(); assert s.live, "set SHADOWCALL_MODE=live"
s.db_path = os.environ.get("SHADOWCALL_DB", "data/smoke.db")
store = Store(s.db_path)
cards = synth.load("data/cards_v1_s7.jsonl")
# 7 training + 3 held-out, preferring varied tags
pick, seen = [], set()
for split, n in (("train", 7), ("heldout", 3)):
    pool = [c for c in cards if c.split == split]
    pool.sort(key=lambda c: (tuple(c.tags) in seen, c.id))
    for c in pool[:n]:
        pick.append(c); seen.add(tuple(c.tags))
p = evalh.make_pipeline(s, store, make_claim_checker(s))
t0 = time.time()
for i, c in enumerate(pick, 1):
    try:
        out = p.run_call(c, "live", chain=False)
        print(f"[{i}/{len(pick)}] {c.id} {c.split} {c.tags}", [(x.subtask, x.teacher_ok, x.shadow_ok, x.corrected) for x in out.subtasks], flush=True)
    except Exception as e:
        print(f"[{i}] {c.id} ERROR", str(e).replace(s.mubit_api_key or "§", "[REDACTED]")[:400], flush=True)
print("elapsed_s", round(time.time() - t0, 1))
