"""Corrections: a frontier mistake becomes a kept correction conversation, or a person's fix."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from shadowcall import synth
from shadowcall.app import create_app
from shadowcall.config import Settings
from shadowcall.llm import Call, LLMResult, MubitClient
from shadowcall.pipeline import KeepCapReached, Pipeline
from shadowcall.store import Store
from shadowcall.subtasks import correction_note, truth_output
from shadowcall.verify import rule_claim_check


class Scripted:
    """Teacher that is wrong first time (drops the late fee) and, if `fixes`, right once corrected."""

    def __init__(self, fixes: bool):
        self.fixes, self.calls = fixes, []

    def complete(self, call: Call) -> LLMResult:
        self.calls.append(call)
        truth = truth_output(call.subtask, call.scenario, call.upstream)
        out = dict(truth)
        if not (call.history and self.fixes):
            out["deposit_gbp"] = int(out.get("deposit_gbp") or 0) + 7  # a deliberate, checkable mistake
        return LLMResult(text=json.dumps(out), request_id=f"mreq_{len(self.calls)}", lane=call.lane)


def _card(policy="v1"):
    return next(c for c in synth.generate(40, 7, policy) if c.split == "train")


def _pipe(fixes, **kw):
    s = Settings()
    s.mode = "mock"
    for k, v in kw.items():
        setattr(s, k, v)
    st = Store(":memory:")
    lane = Scripted(fixes)
    return Pipeline(s, st, {"teacher": lane, "shadow": lane}, rule_claim_check), st, lane


def test_correction_turn_is_kept_as_one_conversation_in_the_same_task():
    p, st, lane = _pipe(fixes=True)
    sc = _card()
    _, s_, _, corrected = p.teacher("policy_check", sc)
    assert corrected and not s_.passed
    probe, turn, keep = lane.calls
    assert probe.record == "metadata" and probe.history is None
    # Same instructions (same Mubit task); the first user message is the original request.
    assert turn.system == probe.system == keep.system
    assert turn.history[0] == {"role": "user", "content": probe.user}
    assert turn.history[1]["role"] == "assistant" and '"deposit_gbp"' in turn.history[1]["content"]
    assert "policy engine v1" in turn.user and "deposit_gbp" in turn.user
    assert turn.record == "metadata" and keep.record == "full" and keep.history == turn.history
    row = st.query("SELECT * FROM corrections")[0]
    assert row["status"] == "kept_correction_turn" and row["source"] == "policy engine v1"
    assert json.loads(row["fixed"])["deposit_gbp"] == truth_output("policy_check", sc)["deposit_gbp"]
    kept = st.query("SELECT phase, record, passed FROM runs WHERE kept=1")
    assert kept == [{"phase": "keep_correction", "record": "full", "passed": 1}]


def test_unfixable_mistake_waits_for_a_person_and_is_never_kept():
    p, st, lane = _pipe(fixes=False)
    p.teacher("form_fill", _card())
    assert [c.record for c in lane.calls] == ["metadata", "metadata"]  # probe + correction turn, nothing full
    row = st.query("SELECT * FROM corrections")[0]
    assert row["status"] == "needs_human" and row["request"]
    assert not st.query("SELECT 1 FROM runs WHERE kept=1")


def test_keep_cap_stops_record_full():
    p, st, lane = _pipe(fixes=True, keep_cap=1)
    cards = [c for c in synth.generate(40, 7, "v1") if c.split == "train"]
    p.teacher("policy_check", cards[0])
    with pytest.raises(KeepCapReached):
        p.teacher("policy_check", cards[1])
    assert len(st.query("SELECT 1 FROM runs WHERE kept=1")) == 1


def test_correction_note_names_fields_and_source():
    n = correction_note("extract", {"intent": "book", "guardian_name": None}, {"intent": "book", "guardian_name": "Ann"},
                        ["guardian_name"], "v2")
    assert "call card" in n and 'guardian_name: you gave null; the call card gives "Ann"' in n
    assert "not one valid JSON" in correction_note("summary", None, {"disposition": "booked"}, ["<malformed>"], "v1")


def test_client_sends_correction_history_in_order():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}})

    c = MubitClient("https://x/v1", "m", "k", transport=httpx.MockTransport(handler), send_temperature=False)
    hist = [{"role": "user", "content": "orig"}, {"role": "assistant", "content": "bad"}]
    c.complete(Call(lane="teacher", subtask="extract", system="S", user="fix it", session_id="s", history=hist))
    assert [m["role"] for m in seen["messages"]] == ["system", "user", "assistant", "user"]
    assert seen["messages"][-1]["content"] == "fix it"


def test_person_approves_fix_and_export_lists_it(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADOWCALL_CORRECTION", "off")  # no correction turn: every mistake needs a person
    from helpers import signed_in
    c = signed_in(str(tmp_path / "t.db"))
    c.post("/api/train", json={"n": 60})
    rows = c.get("/api/corrections?limit=200").json()
    todo = [r for r in rows if r["status"] == "needs_human"]
    assert todo and all(r["source"] for r in todo)
    r = c.post(f"/api/corrections/{todo[0]['id']}/approve", json={"by": "Ibad"}).json()
    assert r["status"] == "human_fixed" and r["source"] == "person (Ibad)"
    exp = c.get("/api/corrections/export").json()
    assert len(exp) == 1 and [m["role"] for m in exp[0]["messages"]] == ["system", "user", "assistant"]
    assert c.post("/api/corrections/999999/approve", json={}).status_code == 404
