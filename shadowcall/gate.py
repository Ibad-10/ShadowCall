"""Per-sub-task promotion gate. A sub-task is served by the small model only after it beats (or
matches, within GATE_MARGIN) the frontier on held-out calls, scored by the verifier — never by
agreement with the frontier. It rolls back on a live quality drop or a policy change."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .store import Store

SAFETY_RULES = {"R5"}  # a single miss on these blocks promotion


@dataclass
class GateDecision:
    promote: bool
    reason: str
    n: int
    teacher_acc: float
    shadow_acc: float


def evaluate(store: Store, s: Settings, subtask: str, policy_version: str, lane: str = "shadow") -> GateDecision:
    rows = store.query(
        "SELECT lane, passed, tags, scenario_id FROM runs WHERE subtask=? AND split='heldout' AND policy_version=? "
        "AND lane IN ('teacher', ?) AND phase='eval'", subtask, policy_version, lane)
    t = [r for r in rows if r["lane"] == "teacher"]
    sh = [r for r in rows if r["lane"] == lane]
    n = min(len(t), len(sh))
    if n < s.gate_min_heldout:
        return GateDecision(False, f"only {n} held-out calls (need {s.gate_min_heldout})", n, 0, 0)
    ta = sum(r["passed"] for r in t) / len(t)
    sa = sum(r["passed"] for r in sh) / len(sh)
    safety_miss = [r for r in sh if not r["passed"] and "red_flag" in (r["tags"] or "")]
    if safety_miss:
        return GateDecision(False, f"{len(safety_miss)} red-flag call(s) failed: safety blocks promotion", n, ta, sa)
    if sa + 1e-9 < ta + s.gate_margin:
        return GateDecision(False, f"small model {sa:.0%} < frontier {ta:.0%} + margin", n, ta, sa)
    return GateDecision(True, f"small model {sa:.0%} >= frontier {ta:.0%} on {n} held-out calls", n, ta, sa)


def try_promote(store: Store, s: Settings, subtask: str, policy_version: str, version: str, lane: str = "shadow"):
    d = evaluate(store, s, subtask, policy_version, lane)
    if d.promote:
        store.set_gate(subtask, "switched", version, policy_version, d.reason)
    return d


def check_rollback(store: Store, s: Settings, subtask: str, policy_version: str) -> str | None:
    g = store.gate_state(subtask)
    if g["state"] != "switched":
        return None
    if g["policy_version"] and g["policy_version"] != policy_version:
        reason = f"policy changed {g['policy_version']} -> {policy_version}: re-qualify"
        store.set_gate(subtask, "shadow", g["version"], policy_version, reason)
        return reason
    rows = store.query("SELECT passed FROM runs WHERE subtask=? AND served=1 AND lane!='teacher' AND phase='live' "
                       "ORDER BY id DESC LIMIT ?", subtask, s.gate_rollback_window)
    if len(rows) >= s.gate_rollback_window:
        acc = sum(r["passed"] for r in rows) / len(rows)
        if acc < s.gate_rollback_floor:
            reason = f"live accuracy {acc:.0%} < floor {s.gate_rollback_floor:.0%} over last {len(rows)}"
            store.set_gate(subtask, "rolled_back", g["version"], policy_version, reason)
            return reason
    return None
