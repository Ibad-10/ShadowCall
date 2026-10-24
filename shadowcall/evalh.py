"""Held-out eval harness. Arms (pre-registered in PREREG.md):
A teacher = the company's frontier model (single shot, as served today)
B shadow  = open base model, prompt only, through Mubit's compat route
C adapter_raw      = adapter trained on every frontier reply ("learning off": no verifier, no corrections)
D adapter_verified = adapter trained on verified replies + corrections ("learning on")
Every arm is scored by the verifier against the truth on the same held-out sessions."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .config import Settings
from .costs import pence
from .llm import MockAdapterState, MockLLM, make_lanes
from .pipeline import Pipeline
from .store import Store
from .subtasks import SUBTASKS

ARMS = ["teacher", "shadow", "adapter_raw", "adapter_verified"]


def mock_adapter(store: Store, verified: bool, subtask: str) -> MockAdapterState:
    """Offline stand-in for a Mubit adapter, built from what this project actually kept."""
    if verified:
        rows = store.query("SELECT tags, policy_version FROM runs WHERE lane='teacher' AND kept=1 AND subtask=?", subtask)
        return MockAdapterState([(json.loads(r["tags"] or "[]"), True, r["policy_version"]) for r in rows])
    rows = store.query("SELECT tags, policy_version, passed FROM runs WHERE lane='teacher' AND split='train' "
                       "AND phase='train' AND record='metadata' AND subtask=?", subtask)
    return MockAdapterState([(json.loads(r["tags"] or "[]"), bool(r["passed"]), r["policy_version"]) for r in rows])


def run_eval(s: Settings, store: Store, scenarios: list, claim_check, imported: dict | None = None) -> dict:
    held = [x for x in scenarios if x.split == "heldout"]
    report: dict = {"n_heldout": len(held), "mode": s.mode, "subtasks": {}}
    lanes = make_lanes(s)
    for st in SUBTASKS:
        arm_lanes = dict(lanes)
        if not s.live:
            arm_lanes["adapter_raw"] = MockAdapterRouter(store, verified=False)
            arm_lanes["adapter_verified"] = MockAdapterRouter(store, verified=True)
        elif "adapter" in lanes:
            arm_lanes["adapter_verified"] = lanes["adapter"]
        res = {}
        for arm in ARMS:
            if arm not in arm_lanes:
                res[arm] = {"available": False}
                continue
            p = Pipeline(s, store, arm_lanes, claim_check)
            stats = defaultdict(float)
            for sc in held:
                out, sco, r, _ = p._run(arm, st, sc, None, "metadata", 0.0, 0, "eval")
                stats["n"] += 1
                stats["passed"] += sco.passed
                stats["pence"] += pence(s, "teacher" if arm == "teacher" else "shadow", r.tokens_in, r.tokens_out)
                stats["latency"] += r.latency_ms
                if "red_flag" in sc.tags:
                    stats["red_n"] += 1
                    stats["red_passed"] += sco.passed
            n = max(stats["n"], 1)
            res[arm] = {"available": True, "n": int(stats["n"]), "accuracy": round(stats["passed"] / n, 3),
                        "pence_per_call": round(stats["pence"] / n, 4), "latency_ms": round(stats["latency"] / n, 1),
                        "red_flag_accuracy": round(stats["red_passed"] / stats["red_n"], 3) if stats["red_n"] else None}
        if imported and st in imported:
            res["adapter_tryouts"] = imported[st]
        report["subtasks"][st] = res
    return report


def to_markdown(report: dict) -> str:
    lines = [f"# Held-out eval ({report['mode']} mode, {report['n_heldout']} held-out calls)", ""]
    if report["mode"] == "mock":
        lines += ["> MOCK MODE: simulated models. These numbers test the harness; they are not results.", ""]
    lines += ["| Sub-task | Arm | Accuracy | Red-flag acc | Pence/call | Latency ms |", "|---|---|---|---|---|---|"]
    for st, arms in report["subtasks"].items():
        for arm, r in arms.items():
            if not r.get("available", True):
                lines.append(f"| {st} | {arm} | n/a | | | |")
                continue
            if arm == "adapter_tryouts":
                continue
            lines.append(f"| {st} | {arm} | {r['accuracy']:.1%} | {r['red_flag_accuracy'] if r['red_flag_accuracy'] is not None else ''} "
                         f"| {r['pence_per_call']:.3f} | {r['latency_ms']:.0f} |")
    return "\n".join(lines) + "\n"


def save(report: dict, outdir: str) -> None:
    Path(outdir).mkdir(parents=True, exist_ok=True)
    Path(outdir, "eval_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path(outdir, "eval_report.md").write_text(to_markdown(report), encoding="utf-8")


class MockAdapterRouter:
    """Offline adapter lane: one simulated adapter per sub-task, rebuilt from the store each call."""

    def __init__(self, store: Store, verified: bool = True):
        self.store, self.verified, self.model = store, verified, "mock-adapter"

    def complete(self, call):
        return MockLLM("adapter", mock_adapter(self.store, self.verified, call.subtask)).complete(call)


def serving_lane(s: Settings) -> str:
    """Which small-model lane the gate promotes and serves: an adapter if one can be called
    (mock, or MUBIT_ADAPTER_* set), else the open base model on Mubit's compat route."""
    return "adapter_verified" if (not s.live or (s.adapter_base_url and s.adapter_model)) else "shadow"


def make_pipeline(s: Settings, store: Store, claim_check) -> Pipeline:
    lanes = make_lanes(s)
    if not s.live:
        lanes["adapter"] = MockAdapterRouter(store, verified=True)
    return Pipeline(s, store, lanes, claim_check, shadow_lane="adapter" if "adapter" in lanes else "shadow")


def import_tryouts(store: Store, cards: list, path: str, claim_check, lane: str = "adapter_tryouts") -> dict:
    """Score adapter replies copied from Mubit's Try models page (one JSON per line:
    {"scenario_id", "subtask", "output"}). Stores them as held-out eval runs for the gate."""
    from .subtasks import build_input, parse_json, score, truth_output
    by_id = {c.id: c for c in cards}
    tally: dict = defaultdict(lambda: [0, 0])
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        j = json.loads(line)
        c = by_id.get(j["scenario_id"])
        if c is None or c.split != "heldout":
            continue  # only held-out cards count
        out = j["output"] if isinstance(j["output"], dict) else parse_json(j["output"])
        st = j["subtask"]
        evidence = build_input("summary", c)
        sco = score(st, out, truth_output(st, c), lambda s_, _t: claim_check(s_, evidence))
        store.insert("runs", scenario_id=c.id, session_id=c.session_id, split=c.split, policy_version=c.policy_version,
                     subtask=st, lane=lane, phase="eval", output=out, passed=int(sco.passed), wrong=sco.wrong_fields,
                     tokens_in=0, tokens_out=0, latency_ms=0, request_id=None, record="tryouts", kept=0, served=0,
                     tags=c.tags)
        tally[st][0] += 1
        tally[st][1] += sco.passed
    return {st: {"n": n, "accuracy": round(p / n, 3)} for st, (n, p) in tally.items()}
