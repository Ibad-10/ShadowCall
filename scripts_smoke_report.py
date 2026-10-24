"""Summarise a smoke-run DB: pass rates per lane and sub-task, latency, tokens, cost."""
import sqlite3, json, statistics as S, sys
db = sys.argv[1]
c = sqlite3.connect(db); c.row_factory = sqlite3.Row
R = [dict(r) for r in c.execute("select * from runs")]
STS = ["extract", "policy_check", "form_fill", "summary"]
print(f"DB {db}: {len(R)} gateway calls, {len({r['scenario_id'] for r in R})} cards")
for lane in ["teacher", "shadow"]:
    rs = [r for r in R if r["lane"] == lane]
    lat = sorted(r["latency_ms"] for r in rs)
    print(f"\n{lane}: calls={len(rs)} tokens_in={sum(r['tokens_in'] for r in rs)} tokens_out={sum(r['tokens_out'] for r in rs)} "
          f"latency p50={S.median(lat):.0f}ms p95={lat[int(0.95*(len(lat)-1))]:.0f}ms max={lat[-1]:.0f}ms")
    for st in STS:
        x = [r for r in R if r["lane"] == lane and r["subtask"] == st and r["phase"] == "live"]
        print(f"  {st:13s} first-shot pass {sum(r['passed'] for r in x)}/{len(x)}  tokens in/out {S.mean(r['tokens_in'] for r in x):.0f}/{S.mean(r['tokens_out'] for r in x):.0f}  p50 {S.median(r['latency_ms'] for r in x):.0f}ms")
print("\nkept (record=full) per sub-task:", {st: sum(1 for r in R if r["kept"] and r["subtask"] == st) for st in STS})
print("keep replays re-verified:", sum(r["passed"] for r in R if r["phase"] == "keep"), "/", sum(1 for r in R if r["phase"] == "keep"))
print("resamples:", sum(1 for r in R if r["phase"] == "resample"), "passed", sum(r["passed"] for r in R if r["phase"] == "resample"))
for r in c.execute("select status, subtask, count(*) n from corrections group by status, subtask"):
    print(" correction", dict(r))
T = [r for r in R if r["lane"] == "teacher"]; Sh = [r for r in R if r["lane"] == "shadow"]
usd = sum(r["tokens_in"] * 2e-6 + r["tokens_out"] * 10e-6 for r in T) + sum(r["tokens_in"] * 0.075e-6 + r["tokens_out"] * 0.3e-6 for r in Sh)
print(f"\nprovider cost est ${usd:.3f} (gpt-6-sol $2/$10, gpt-oss-20b $0.075/$0.30 per Mtok); Mubit runs {len(R)} x $0.005 = ${len(R)*0.005:.2f}")
tl = [r for r in T if r["phase"] == "live"]; n = len({r["scenario_id"] for r in tl})
print(f"per phone call, 4 sub-tasks single shot, provider tokens only at 75p/$: frontier {sum(r['tokens_in']*2e-6+r['tokens_out']*10e-6 for r in tl)/n*75:.3f}p, open model {sum(r['tokens_in']*0.075e-6+r['tokens_out']*0.3e-6 for r in Sh)/n*75:.4f}p; Mubit adds 0.375p per call made")
print("\nfailures (first shot):")
for r in R:
    if r["phase"] == "live" and not r["passed"]:
        print(f"  {r['lane']:7s} {r['subtask']:12s} {r['scenario_id']} {r['tags']} wrong={r['wrong']}")
