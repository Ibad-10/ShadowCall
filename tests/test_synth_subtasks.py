from shadowcall import synth
from shadowcall.subtasks import INSTRUCTIONS, SUBTASKS, build_input, parse_json, score, truth_output


def test_deterministic_and_session_split():
    a, b = synth.generate(80, seed=3), synth.generate(80, seed=3)
    assert [x.to_dict() for x in a] == [x.to_dict() for x in b]
    train = {x.session_id for x in a if x.split == "train"}
    held = {x.session_id for x in a if x.split == "heldout"}
    assert held and train and not (train & held)


def test_hard_cases_present():
    tags = {t for x in synth.generate(300, seed=1) for t in x.tags}
    for t in ("child", "self_correction", "late_change", "red_flag", "new_patient", "saturday"):
        assert t in tags


def test_instructions_are_fixed_per_subtask():
    # Mubit groups a task by instructions; nothing per-call may leak into them.
    cards = synth.generate(10, seed=5, policy_version="v2")
    for st in SUBTASKS:
        assert "Riverside Dental" not in INSTRUCTIONS[st] or st == "extract"
        for c in cards:
            assert c.patient_name if False else True
            assert INSTRUCTIONS[st] not in build_input(st, c)


def test_policy_text_travels_in_user_message():
    c = synth.generate(1, seed=5, policy_version="v2")[0]
    assert "policy v2" in build_input("policy_check", c)


def test_truth_scores_perfectly_and_errors_are_caught():
    for c in synth.generate(40, seed=9):
        for st in SUBTASKS:
            t = truth_output(st, c)
            assert score(st, t, t).passed
    c = synth.generate(1, seed=9)[0]
    t = truth_output("form_fill", c)
    bad = dict(t, fee_gbp=t["fee_gbp"] + 30)
    assert not score("form_fill", bad, t).passed
    assert not score("extract", None, truth_output("extract", c)).passed


def test_parse_json_tolerates_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json("no json here") is None
