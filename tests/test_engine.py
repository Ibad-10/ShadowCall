from datetime import datetime

from shadowcall.policy.engine import Request, decide, get_policy

NOW = datetime(2026, 10, 26, 9, 0)  # Monday


def d(req, v="v1", diary=()):
    return decide(req, get_policy(v), NOW, list(diary))


def test_sunday_is_closed():
    r = d(Request("book", treatment="checkup", preferred_date="2026-11-01", preferred_time="10:00"))
    assert r.decision == "deny" and "R1" in r.rule_ids


def test_new_patient_hygiene_becomes_checkup():
    r = d(Request("book", is_new_patient=True, treatment="hygiene", preferred_date="2026-10-27", preferred_time="10:00"))
    assert r.decision == "allow" and r.treatment == "checkup" and r.alternative == "checkup" and "R3" in r.rule_ids


def test_late_cancel_costs_30():
    r = d(Request("cancel", existing_appointment="2026-10-26T15:00"))
    assert r.fee_gbp == 30 and "R4" in r.rule_ids and r.disposition == "cancelled"


def test_early_cancel_free():
    assert d(Request("cancel", existing_appointment="2026-10-29T15:00")).fee_gbp == 0


def test_red_flag_escalates_before_anything():
    r = d(Request("emergency", red_flags=["swelling_breathing"], preferred_date="2026-10-26"))
    assert r.decision == "escalate" and r.action == "urgent_999" and r.rule_ids == ["R5"]


def test_child_needs_guardian():
    base = dict(treatment="checkup", preferred_date="2026-10-27", preferred_time="10:00", age=9)
    assert d(Request("book", **base)).decision == "deny"
    ok = d(Request("book", guardian_name="Sam Khan", **base))
    assert ok.decision == "allow" and ok.guardian_required and "R6" in ok.rule_ids


def test_clash_denied():
    r = d(Request("book", treatment="checkup", preferred_date="2026-10-27", preferred_time="10:00"),
          diary=[("2026-10-27T10:15", 30)])
    assert "R8" in r.rule_ids


def test_v2_changes():
    hyg = Request("book", treatment="hygiene", preferred_date="2026-10-27", preferred_time="10:00")
    assert d(hyg, "v1").duration_min == 30 and d(hyg, "v2").duration_min == 45
    newp = Request("book", is_new_patient=True, treatment="checkup", preferred_date="2026-10-27", preferred_time="10:00")
    assert d(newp, "v1").deposit_gbp == 0 and d(newp, "v2").deposit_gbp == 25
    sat = Request("book", treatment="checkup", preferred_date="2026-10-31", preferred_time="11:45")
    assert d(sat, "v1").decision == "allow" and d(sat, "v2").decision == "deny"


def test_emergency_without_time_gets_first_free_slot():
    r = d(Request("emergency", treatment="emergency", preferred_date="2026-10-26"), diary=[("2026-10-26T09:00", 30)])
    assert r.decision == "allow" and r.start == "2026-10-26T09:30"


def test_past_and_far_future_denied():
    assert "R7" in d(Request("book", treatment="checkup", preferred_date="2026-10-20", preferred_time="10:00")).rule_ids
    assert "R7" in d(Request("book", treatment="checkup", preferred_date="2027-03-01", preferred_time="10:00")).rule_ids


def test_r6_listed_even_when_slot_refused():
    from datetime import datetime
    from shadowcall.policy.engine import POLICIES, Request, decide
    r = Request(intent="book", patient_name="A", age=10, treatment="checkup", preferred_date="2026-11-01",
                preferred_time="10:00", guardian_name="B")  # a Sunday: closed
    d = decide(r, POLICIES["v1"], datetime(2026, 10, 26, 9, 0), [])
    assert d.decision == "deny" and "R6" in d.rule_ids and "R1" in d.rule_ids and d.guardian_required


def test_claim_check_normalises_clock_times():
    from shadowcall.verify import rule_claim_check
    assert rule_claim_check("Booked for 8:00 a.m. and 2:30 pm.", '{"a": "08:00", "b": "2026-11-08T14:30"}')
    assert not rule_claim_check("Booked for 9:15.", '{"a": "08:00"}')
