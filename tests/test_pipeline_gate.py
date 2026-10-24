import json

from shadowcall import evalh, gate, synth
from shadowcall.config import Settings
from shadowcall.llm import make_lanes
from shadowcall.pipeline import Pipeline
from shadowcall.store import Store
from shadowcall.subtasks import SUBTASKS
from shadowcall.verify import rule_claim_check


def setup(n=160, seed=7, policy="v1"):
    s = Settings()
    s.mode = "mock"
    st = Store(":memory:")
    cards = synth.generate(n, seed, policy)
    p = Pipeline(s, st, make_lanes(s), rule_claim_check)
    for c in cards:
        if c.split == "train":
            p.run_call(c, "train")
    return s, st, cards


def test_only_verified_teacher_replies_are_kept():
    s, st, _ = setup()
    kept = st.query("SELECT passed FROM runs WHERE kept=1")
    assert kept and all(r["passed"] for r in kept)
    # every kept row was sent with full recording; every unkept teacher row with metadata
    assert not st.query("SELECT 1 FROM runs WHERE kept=1 AND record!='full'")
    assert not st.query("SELECT 1 FROM runs WHERE kept=0 AND record='full'")


def test_frontier_errors_become_corrections():
    _, st, _ = setup()
    corr = st.query("SELECT * FROM corrections")
    assert corr
    for c in corr:
        assert json.loads(c["bad"]) != json.loads(c["fixed"])


def test_heldout_never_kept():
    s, st, cards = setup()
    evalh.run_eval(s, st, cards, rule_claim_check)
    assert not st.query("SELECT 1 FROM runs WHERE split='heldout' AND (kept=1 OR record='full')")


def test_gate_promotes_only_on_heldout_evidence():
    s, st, cards = setup()
    assert not gate.evaluate(st, s, "extract", "v1", "adapter_verified").promote  # no eval yet
    evalh.run_eval(s, st, cards, rule_claim_check)
    d = gate.evaluate(st, s, "extract", "v1", "adapter_verified")
    assert d.n >= s.gate_min_heldout


def test_gate_blocks_worse_model_and_safety_misses():
    s = Settings()
    st = Store(":memory:")
    for i in range(25):
        st.insert("runs", subtask="extract", split="heldout", policy_version="v1", phase="eval", lane="teacher",
                  passed=1, tags="[]", scenario_id=str(i))
        st.insert("runs", subtask="extract", split="heldout", policy_version="v1", phase="eval", lane="shadow",
                  passed=int(i % 3 != 0), tags="[]", scenario_id=str(i))
    assert not gate.evaluate(st, s, "extract", "v1").promote
    st2 = Store(":memory:")
    for i in range(25):
        st2.insert("runs", subtask="extract", split="heldout", policy_version="v1", phase="eval", lane="teacher",
                   passed=0, tags="[]", scenario_id=str(i))
        st2.insert("runs", subtask="extract", split="heldout", policy_version="v1", phase="eval", lane="shadow",
                   passed=int(i != 0), tags='["red_flag"]' if i == 0 else "[]", scenario_id=str(i))
    d = gate.evaluate(st2, s, "extract", "v1")
    assert not d.promote and "safety" in d.reason


def test_policy_change_rolls_back_switched_subtask():
    s = Settings()
    st = Store(":memory:")
    st.set_gate("form_fill", "switched", "adapter-v1", "v1", "test")
    reason = gate.check_rollback(st, s, "form_fill", "v2")
    assert reason and st.gate_state("form_fill")["state"] == "shadow"


def test_eval_report_has_all_arms_and_mock_warning():
    s, st, cards = setup()
    rep = evalh.run_eval(s, st, cards, rule_claim_check)
    for t in SUBTASKS:
        assert set(evalh.ARMS) <= set(rep["subtasks"][t])
    assert "MOCK MODE" in evalh.to_markdown(rep)


def test_switched_subtask_served_by_small_model_with_audit():
    s, st, cards = setup()
    s.audit_rate = 0.0
    st.set_gate("summary", "switched", "adapter-v1", "v1", "test")
    lanes = make_lanes(s)
    lanes["adapter"] = evalh.MockAdapterRouter(st)
    p = Pipeline(s, st, lanes, rule_claim_check, shadow_lane="adapter")
    out = p.run_call(cards[0], "live")
    by = {x.subtask: x.served_by for x in out.subtasks}
    assert by["summary"] == "adapter" and by["extract"] == "teacher"


def test_fast_refresh_policy_change_cycle():
    """v1 adapter switched -> policy v2 rolls it back -> stale on v2 -> v2 examples -> re-promoted."""
    s, st, cards = setup()
    evalh.run_eval(s, st, cards, rule_claim_check)
    assert gate.try_promote(st, s, "form_fill", "v1", "a-v1", "adapter_verified").promote
    assert gate.check_rollback(st, s, "form_fill", "v2")
    v2 = synth.generate(160, 21, "v2")
    evalh.run_eval(s, st, v2, rule_claim_check)
    stale = gate.evaluate(st, s, "form_fill", "v2", "adapter_verified")
    assert not stale.promote
    p = Pipeline(s, st, make_lanes(s), rule_claim_check)
    for c in v2:
        if c.split == "train":
            p.run_call(c, "train")
    st.db.execute("DELETE FROM runs WHERE phase='eval' AND policy_version='v2'")
    evalh.run_eval(s, st, v2, rule_claim_check)
    assert gate.try_promote(st, s, "form_fill", "v2", "a-v2", "adapter_verified").promote


def test_import_tryouts_scores_heldout_only(tmp_path):
    from shadowcall.subtasks import truth_output
    s = Settings()
    st = Store(":memory:")
    cards = synth.generate(60, 7, "v1")
    held = [c for c in cards if c.split == "heldout"][:3]
    train = [c for c in cards if c.split == "train"][0]
    lines = [json.dumps({"scenario_id": c.id, "subtask": "form_fill", "output": json.dumps(truth_output("form_fill", c))})
             for c in held]
    lines.append(json.dumps({"scenario_id": train.id, "subtask": "form_fill", "output": "{}"}))
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join(lines), encoding="utf-8")
    r = evalh.import_tryouts(st, cards, str(f), rule_claim_check)
    assert r == {"form_fill": {"n": 3, "accuracy": 1.0}}
