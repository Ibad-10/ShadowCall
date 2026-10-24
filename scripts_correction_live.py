"""Live check of correction turns on the cards the frontier got wrong in smoke run 2.
Training card: full teacher() path (probe, correction turn, keep replay), capped at 1 keep.
Held-out cards: probe + correction turn, both record=metadata (never kept). Never prints keys."""
import json, os
from shadowcall.config import get_settings
from shadowcall.store import Store
from shadowcall import synth, evalh
from shadowcall.subtasks import correction_note
from shadowcall.verify import make_claim_checker

s = get_settings(); assert s.live, "set SHADOWCALL_MODE=live"
s.db_path = os.environ.get("SHADOWCALL_DB", "data/correct_live.db"); s.keep_cap = 1
store = Store(s.db_path)
cards = {c.id: c for c in synth.load("data/cards_v1_s7.jsonl")}
p = evalh.make_pipeline(s, store, make_claim_checker(s))
red = lambda x: str(x).replace(s.mubit_api_key or "§", "[REDACTED]")

sc = cards["call-v1-0002-8832"]
out, s_, res, corrected = p.teacher("form_fill", sc)
print("TRAIN 0002 form_fill probe_passed", s_.passed, "wrong", s_.wrong_fields, "corrected", corrected)
for r in store.query("SELECT status, source, fixed, request_id FROM corrections"):
    print("  correction:", r["status"], r["source"], r["fixed"], r["request_id"])

for cid, st in (("call-v1-0010-3207", "policy_check"), ("call-v1-0006-1647", "form_fill"), ("call-v1-0010-3207", "form_fill")):
    sc = cards[cid]
    try:
        o, sc1, r1, truth = p._run("teacher", st, sc, None, "metadata", 0.0, 0, "probe_heldout")
        line = f"HELDOUT {cid} {st} probe_passed {sc1.passed} wrong {sc1.wrong_fields}"
        if not sc1.passed:
            note = correction_note(st, o, truth, sc1.wrong_fields, sc.policy_version)
            o2, sc2, r2, _ = p._run("teacher", st, sc, None, "metadata", 0.0, 0, "correct_heldout",
                                    correction=(r1.text, note))
            line += f" -> correction_turn_passed {sc2.passed} wrong {sc2.wrong_fields}"
        print(line)
    except Exception as e:
        print("ERROR", cid, st, red(e)[:300])
rows = store.query("SELECT phase, record, kept, passed, tokens_in, tokens_out FROM runs")
print("calls", len(rows), "full", sum(r["record"] == "full" for r in rows), "kept", sum(r["kept"] for r in rows),
      "tok_in", sum(r["tokens_in"] for r in rows), "tok_out", sum(r["tokens_out"] for r in rows))
