"""Live run: verified example collection, then held-out eval, through Mubit. Never prints keys.

  python scripts_live_run.py train --target 30      # training cards only (split == "train")
  python scripts_live_run.py eval --tag base         # held-out cards only, record=metadata (never kept)
  python scripts_live_run.py report                  # writes data/live_results.json + .md

Spend guard: stops before an estimated US$ total (provider tokens + Mubit's per-request fee) above
SPEND_STOP_USD (default 12). Groq pacing: stays under ~7,000 tokens a minute on the shadow lane."""
from __future__ import annotations

import json, os, statistics, sys, time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from shadowcall import evalh, synth
from shadowcall.config import get_settings
from shadowcall.costs import pence
from shadowcall.store import Store
from shadowcall.subtasks import SUBTASKS
from shadowcall.verify import make_claim_checker

DATA = Path(__file__).resolve().parent / "data"
CARDS = Path(os.environ.get("LIVE_CARDS", str(DATA / "cards_v1_s7.jsonl")))
PHASES = DATA / "live_phases.json"  # which card file each eval phase used
USED_BEFORE = 10  # cards 0-9 went through the smoke runs; start fresh sessions after them
# US$ per 1M tokens and per Mubit request, as used in the earlier smoke report.
USD = {"teacher": (2.0, 10.0), "shadow": (0.075, 0.30)}
MUBIT_FEE = 0.005
SPEND_STOP = float(os.environ.get("SPEND_STOP_USD", "12"))

s = get_settings()
assert s.live and s.mubit_api_key, "set SHADOWCALL_MODE=live and MUBIT_API_KEY"
s.db_path = os.environ.get("SHADOWCALL_DB", str(DATA / "live_run.db"))
store = Store(s.db_path)
HDR_LOG = DATA / "live_headers.jsonl"
red = lambda x: str(x).replace(s.mubit_api_key, "[REDACTED]")


def spend_usd(db=store) -> float:
    tot = 0.0
    for r in db.query("SELECT lane, COUNT(*) n, SUM(tokens_in) ti, SUM(tokens_out) tout FROM runs GROUP BY lane"):
        a, b = USD["teacher" if r["lane"] == "teacher" else "shadow"]
        tot += (r["ti"] or 0) * a / 1e6 + (r["tout"] or 0) * b / 1e6 + r["n"] * MUBIT_FEE
    return tot


class Spy:
    """Wraps a lane's httpx client: records Mubit's response headers and the reply's model field
    (the only signals we can see of who served a call), and paces the Groq lane."""

    def __init__(self, lane, client, tpm=None):
        self.lane, self.http, self.tpm, self.win = lane, client._http, tpm, deque()
        client._http = self

    def post(self, url, **kw):
        if self.tpm:
            while True:
                now = time.time()
                while self.win and now - self.win[0][0] > 60:
                    self.win.popleft()
                if sum(t for _, t in self.win) < self.tpm:
                    break
                time.sleep(1.0)
        r = self.http.post(url, **kw)
        rec = {"ts": time.time(), "lane": self.lane, "status": r.status_code,
               "headers": {k: v for k, v in r.headers.items() if k.startswith(("x-middleware", "x-ratelimit", "x-served", "openai-model"))}}
        try:
            j = r.json()
            rec["model"] = j.get("model")
            rec["extra_keys"] = sorted(set(j) - {"id", "object", "created", "model", "choices", "usage", "system_fingerprint", "service_tier"})
            used = (j.get("usage") or {}).get("total_tokens", 0)
        except Exception:
            used = 0
        if self.tpm:
            self.win.append((time.time(), used or 900))
        with HDR_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        return r


def pipeline():
    p = evalh.make_pipeline(s, store, make_claim_checker(s))
    Spy("teacher", p.lanes["teacher"])
    Spy("shadow", p.lanes["shadow"], tpm=int(os.environ.get("GROQ_TPM_BUDGET", "6500")))
    return p


def kept(st):
    return store.query("SELECT COUNT(*) n FROM runs WHERE subtask=? AND kept=1 AND passed=1", st)[0]["n"]


def train(target: int):
    s.keep_cap = target + 2  # hard backstop on record=full sends per sub-task in this database
    p = pipeline()
    cards = [c for c in synth.load(str(CARDS))[USED_BEFORE:] if c.split == "train"]
    for i, c in enumerate(cards, 1):
        if all(kept(st) >= target for st in SUBTASKS):
            break
        if spend_usd() > SPEND_STOP:
            print("SPEND STOP", round(spend_usd(), 2)); break
        for st in SUBTASKS:
            if kept(st) >= target:
                continue
            try:
                out, sc_, res, corrected = p.teacher(st, c, None, "train")
            except Exception as e:
                print("ERROR", c.id, st, red(e)[:200]); continue
        print(f"[{i}] {c.id} kept", {st: kept(st) for st in SUBTASKS}, f"spend ${spend_usd():.2f}", flush=True)
    assert not store.query("SELECT 1 FROM runs WHERE split='heldout' AND (kept=1 OR record='full')"), "held-out leak"


def evaluate(tag: str, limit: int | None):
    p = pipeline()
    held = [c for c in synth.load(str(CARDS)) if c.split == "heldout"][:limit]
    phase = f"eval_{tag}"
    ph = json.loads(PHASES.read_text()) if PHASES.exists() else {}
    ph[phase] = CARDS.name
    PHASES.write_text(json.dumps(ph, indent=2))
    done = {(r["scenario_id"], r["subtask"], r["lane"]) for r in store.query("SELECT scenario_id, subtask, lane FROM runs WHERE phase=?", phase)}
    for i, c in enumerate(held, 1):
        if spend_usd() > SPEND_STOP:
            print("SPEND STOP", round(spend_usd(), 2)); break
        for st in SUBTASKS:
            for lane in ("teacher", "shadow"):
                if (c.id, st, lane) in done:
                    continue
                try:
                    p._run(lane, st, c, None, "metadata", 0.0, 0, phase)
                except Exception as e:
                    print("ERROR", c.id, st, lane, red(e)[:200])
        print(f"[{i}/{len(held)}] {c.id} spend ${spend_usd():.2f}", flush=True)
    assert not store.query("SELECT 1 FROM runs WHERE split='heldout' AND (kept=1 OR record='full')"), "held-out leak"


def med(xs):
    return round(statistics.median(xs), 4) if xs else None


def report():
    out = {"label": "Live — real Mubit calls", "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "teacher_model": s.teacher_model, "shadow_model": s.shadow_model, "cards": CARDS.name,
           "scoring": "ShadowCall's own checker (call card + policy engine v1); the frontier is never the judge",
           "pence_note": "provider tokens only, at 75p per US$; Mubit's per-request fee is not included",
           "findings": [
               "Red-flag set, extract: every reply (both models) fails on preferred_date. The card truth sets it to null for a "
               "red-flag emergency, but the extract prompt only says 'emergency without red flags -> today'. That is a gap "
               "in our spec, not a model error; the red_flags field itself is scored separately as red-flag misses.",
               "Held-out set cards_v1_s7 has no red-flag calls, so red-flag numbers come only from the 15-card supplementary set (small n).",
               "Some red-flag small-model calls are missing (n < 15): Groq's 200,000 tokens-a-day limit was reached; not retried.",
               "Arms C/D (adapter) not run: Mubit gives the inference key no adapter endpoint, kept count or training status."],
           "training": {}, "evals": {}, "spend_usd_estimate": round(spend_usd(), 2)}
    for st in SUBTASKS:
        rows = store.query("SELECT phase, passed, record FROM runs WHERE subtask=? AND split='train'", st)
        out["training"][st] = {
            "probes": sum(r["phase"] == "train" for r in rows),
            "probe_passed": sum(r["phase"] == "train" and r["passed"] for r in rows),
            "correction_turns": sum(r["phase"] == "correct" for r in rows),
            "correction_passed": sum(r["phase"] == "correct" and r["passed"] for r in rows),
            "record_full_sent": sum(r["record"] == "full" for r in rows),
            "record_full_reverified": kept(st)}
    for (phase,) in [(r["phase"],) for r in store.query("SELECT DISTINCT phase FROM runs WHERE phase LIKE 'eval_%'")]:
        ev = {"subtasks": {}, "per_call": {}}
        rows = store.query("SELECT * FROM runs WHERE phase=?", phase)
        ts = [r["ts"] for r in rows]
        ev["from_utc"] = datetime.fromtimestamp(min(ts), timezone.utc).isoformat(timespec="seconds")
        ev["to_utc"] = datetime.fromtimestamp(max(ts), timezone.utc).isoformat(timespec="seconds")
        per_card = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0]))
        for st in SUBTASKS:
            ev["subtasks"][st] = {}
            for lane in ("teacher", "shadow"):
                rs = [r for r in rows if r["subtask"] == st and r["lane"] == lane]
                redr = [r for r in rs if "red_flag" in json.loads(r["tags"] or "[]")]
                pz = [pence(s, lane, r["tokens_in"], r["tokens_out"]) for r in rs]
                ev["subtasks"][st][lane] = {
                    "n": len(rs), "passed": sum(r["passed"] for r in rs),
                    "accuracy": round(sum(r["passed"] for r in rs) / len(rs), 3) if rs else None,
                    "median_latency_ms": med([r["latency_ms"] for r in rs]),
                    "median_pence": med(pz), "red_flag_n": len(redr),
                    "failed_on_red_flag_calls": sum(not r["passed"] for r in redr),
                    # a red-flag miss: the emergency itself was missed (extract: red_flags field wrong;
                    # other jobs: any failure on a red-flag call, since that is the safety-relevant answer)
                    "red_flag_misses": sum(("red_flags" in json.loads(r["wrong"] or "[]")) if st == "extract" else (not r["passed"]) for r in redr)}
                for r, pp in zip(rs, pz):
                    c = per_card[lane][r["scenario_id"]]
                    c[0] += pp; c[1] += r["latency_ms"]; c[2] += 1
        for lane in ("teacher", "shadow"):
            full = [v for v in per_card[lane].values() if v[2] == len(SUBTASKS)]
            ev["per_call"][lane] = {"n_calls": len(full), "median_pence": med([v[0] for v in full]),
                                    "median_latency_ms_4_subtasks_sequential": med([v[1] for v in full])}
        ph = json.loads(PHASES.read_text()) if PHASES.exists() else {}
        ev["cards"] = ph.get(phase, "cards_v1_s7.jsonl")
        sh = [r for r in rows if r["lane"] == "shadow"]
        ev["shadow_calls_over_10s"] = sum(r["latency_ms"] > 10000 for r in sh)
        ev["latency_note"] = (f"{ev['shadow_calls_over_10s']} of {len(sh)} small-model calls took over 10 s while waiting on "
                              "Groq's 8,000 tokens-a-minute limit; medians are shown so these waits barely move them, "
                              "but the summed per-call time includes them")
        out["evals"][phase] = ev
    (DATA / "live_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    md = [f"# {out['label']}", "", f"Generated {out['generated_utc']} (UTC). Frontier `{s.teacher_model}` vs small `{s.shadow_model}`, both through Mubit. Scored by our own checker.", ""]
    for phase, ev in out["evals"].items():
        md += [f"## {phase} ({ev['from_utc']} to {ev['to_utc']} UTC, cards `{ev['cards']}`)", "", f"Note: {ev['latency_note']}.", "", "| Sub-task | Lane | n | Correct | Accuracy | Median latency ms | Median pence | Red-flag misses / red-flag calls | Failed on red-flag calls |", "|---|---|---|---|---|---|---|---|---|"]
        for st, lanes in ev["subtasks"].items():
            for lane, v in lanes.items():
                md.append(f"| {st} | {lane} | {v['n']} | {v['passed']} | {v['accuracy']:.1%} | {v['median_latency_ms']:.0f} | {v['median_pence']:.4f} | {v['red_flag_misses']} / {v['red_flag_n']} | {v['failed_on_red_flag_calls']} |")
        for lane, v in ev["per_call"].items():
            md.append(f"\nPer call ({lane}, all 4 sub-tasks, n={v['n_calls']}): median {v['median_pence']}p, median {v['median_latency_ms_4_subtasks_sequential']} ms summed.")
        md.append("")
    md += ["## Training sends", "", "| Sub-task | Probes | Probe passed | Correction turns | Fixed | record=full sent | Re-verified |", "|---|---|---|---|---|---|---|"]
    for st, v in out["training"].items():
        md.append(f"| {st} | {v['probes']} | {v['probe_passed']} | {v['correction_turns']} | {v['correction_passed']} | {v['record_full_sent']} | {v['record_full_reverified']} |")
    md += ["", "## Findings", ""] + [f"- {f}" for f in out["findings"]]
    md += ["", f"Estimated spend for this run: ${out['spend_usd_estimate']} (provider list prices + $0.005 per Mubit request; an estimate, not a bill).", f"Pence: {out['pence_note']}."]
    (DATA / "live_results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "train":
        train(int(sys.argv[sys.argv.index("--target") + 1]) if "--target" in sys.argv else 30)
    elif cmd == "eval":
        evaluate(sys.argv[sys.argv.index("--tag") + 1], int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None)
    elif cmd == "report":
        report()
    elif cmd == "spend":
        print(round(spend_usd(), 3))
