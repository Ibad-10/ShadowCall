"""Replay mode: the console filled from the real live run (data/live_replay.json), offline and read-only."""
import json
import re

import pytest

from helpers import signed_in
from shadowcall import replay
from shadowcall.config import ROOT

DATA = ROOT / "data" / "live_replay.json"


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADOWCALL_MODE", "replay")
    for k in ("MUBIT_API_KEY", "MUBIT_API_KEY_RAW", "ELEVENLABS_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return signed_in(str(tmp_path / "r.db"))


def test_replay_file_is_committed_and_key_free():
    text = DATA.read_text(encoding="utf-8")
    assert not re.search(r"(?i)authorization|bearer |x-api-key|xi-api-key|sk-[A-Za-z0-9]{16}|mbt_", text)
    d = json.loads(text)
    assert all(r["request_id"].startswith("mreq_") for r in d["runs"] if r["request_id"])
    assert not [r for r in d["runs"] if r["split"] == "heldout" and (r["kept"] or r["record"] == "full")]
    assert {r["scenario_id"] for r in d["runs"]} <= set(d["cards"])


def test_replay_check_refuses_secrets():
    with pytest.raises(ValueError):
        replay.check_clean('{"h": "Authorization: Bearer abc"}', [])
    with pytest.raises(ValueError):
        replay.check_clean('{"x": "zz-secret-value-zz"}', ["zz-secret-value-zz"])


def test_gate_is_decided_by_the_real_scores(c):
    sm = c.get("/api/summary").json()
    assert sm["mode"] == "replay" and sm["replay"]["label"].startswith("Replaying real Mubit calls from 24 Oct")
    states = {t: v["gate"]["state"] for t, v in sm["subtasks"].items()}
    assert states == {"extract": "shadow", "policy_check": "shadow", "form_fill": "shadow", "summary": "switched"}
    held = {h["lane"]: (h["acc"], h["n"]) for h in sm["subtasks"]["form_fill"]["heldout"]}
    assert held["teacher"][1] == held["shadow"][1] == 43
    assert "red-flag" in sm["subtasks"]["summary"]["gate"]["reason"]
    rp = sm["replay"]
    assert 0 < rp["pence_served"] < rp["pence_frontier"] and rp["heldout_calls"] == 43


def test_pages_have_real_data(c):
    assert len(c.get("/api/disagreements?limit=200").json()) > 0
    cors = c.get("/api/corrections").json()
    assert sum(r["status"] == "kept_correction_turn" for r in cors) == 17
    assert sum(r["status"] == "needs_human" for r in cors) == 1
    calls = c.get("/api/calls").json()
    d = c.get(f"/api/calls/{calls['rows'][0]['id']}").json()
    assert d["transcript"] and d["subtasks"]
    rep = c.get("/api/eval/report").json()
    assert rep["mode"] == "replay" and rep["subtasks"]["summary"]["shadow"]["accuracy"] == 1.0
    assert c.get("/api/live-results").json().get("evals")
    assert c.get("/api/settings").json()["replay"]


def test_replay_is_read_only(c):
    for path, body in [("/api/train", {}), ("/api/eval", {}), ("/api/live", {}), ("/api/policy", {"version": "v2"}),
                       ("/api/refresh", {"version": "v2"}), ("/api/chat", {"card_id": "x"})]:
        assert c.post(path, json=body).status_code == 409, path


def test_feed_replays_real_calls_with_a_rising_cursor(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADOWCALL_MODE", "replay")
    from shadowcall.app import State
    st = State(str(tmp_path / "f.db"))
    t = [0.0]
    st.clock = replay.Clock(st.store, speed=60, now=lambda: t[0])
    lp, vt = st.clock.position()
    assert lp == 0 and vt == st.clock.t0
    t[0] = (st.clock.t1 - st.clock.t0) / 60 + 1  # one full loop later
    assert st.clock.position()[0] == 1
