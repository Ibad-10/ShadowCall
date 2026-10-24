"""The four sub-tasks of a call. Each has FIXED instructions, so Mubit sees each as one task
(instructions + tools + tool choice + output format + model define a task). Everything that
changes per call, including the policy text, goes in the user message."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .policy.engine import Decision, Request, decide, get_policy

SUBTASKS = ["extract", "policy_check", "form_fill", "summary"]

INSTRUCTIONS = {
    "extract": (
        "You read a phone call transcript between a dental practice receptionist and a caller. "
        "Return JSON only with keys: intent (book|reschedule|cancel|emergency|enquiry), patient_name, "
        "is_new_patient (bool), age (int or null), treatment (checkup|hygiene|filling|emergency|whitening_consult|null), "
        "preferred_date (YYYY-MM-DD or null), preferred_time (HH:MM 24h or null), guardian_name (or null), "
        "red_flags (list from: swelling_breathing, swelling_eye, uncontrolled_bleeding, head_injury_unconscious), "
        "existing_appointment (YYYY-MM-DDTHH:MM or null). If the caller corrects themselves, use the final answer. "
        "For an emergency without red flags, preferred_date is today and preferred_time is null."
    ),
    "policy_check": (
        "You check a dental booking request against the practice policy given in the message. "
        "Return JSON only with keys: decision (allow|deny|escalate), rule_ids, fee_gbp (int), deposit_gbp (int), "
        "reason (one sentence for the caller). "
        "rule_ids lists only rules that change or constrain this request, never rules that were checked and simply met: "
        "R5 if there are red flags (then decision escalate and nothing else). An enquiry (no booking, move or "
        "cancellation) is decision allow with no rule_ids. Otherwise: R3 if a new patient is switched to a "
        "check-up or must pay a deposit; R4 if a late-change fee applies; R6 if a booking or move is for a patient under 16; and, when the "
        "slot is refused (decision deny), R7 (outside the booking window), R1 (outside opening hours) or R8 (diary clash), "
        "MISSING_SLOT (no date or time and none free that day) or GUARDIAN_MISSING (under 16 with no guardian named). "
        "If the caller gives a date but no time, use the first free slot that day. "
        "fee_gbp is only the late-change fee (R4), never the treatment price. deposit_gbp is only the new-patient deposit. "
        "Use only the policy text in the message."
    ),
    "form_fill": (
        "You fill the practice's booking form from a request, the policy and the diary given in the message. "
        "Return JSON only with keys: action (create|move|cancel|none|urgent_999), treatment, start (YYYY-MM-DDTHH:MM or null), "
        "duration_min (int or null), price_gbp (int), deposit_gbp (int), fee_gbp (int), guardian_required (bool). "
        "action is create for a new booking, move for a reschedule, cancel for a cancellation, urgent_999 for red flags, "
        "and none when the slot is refused or the call is only an enquiry. treatment is the treatment actually booked "
        "(a new patient asking for hygiene or a filling gets a checkup); give it even when the slot is refused; "
        "it is null only for cancel, urgent_999 and enquiries. "
        "If a date is given without a time, use the first free slot that day. start, duration_min and price_gbp are set "
        "only for create and move (otherwise null, null and 0). fee_gbp is only the late-change fee; deposit_gbp only the "
        "new-patient deposit; guardian_required is true when a booking or move (refused or not) is for a patient under 16."
    ),
    "summary": (
        "You write the after-call wrap-up for a dental practice. Return JSON only with keys: disposition "
        "(booked|rescheduled|cancelled|info_only|escalated_urgent|no_slot), summary (max 2 sentences, only facts from "
        "the transcript and outcome), follow_ups (list of short strings)."
    ),
}

OUTPUT_FORMAT = {"type": "json_object"}


def _diary_for(diary: list, day: str | None) -> list:
    if not day:
        return []
    return [d for d in diary if d[0].startswith(day)]


def build_input(subtask: str, scenario, upstream: dict | None = None) -> str:
    """User message for a sub-task. `upstream` is the extracted request; defaults to ground truth
    (teacher forcing), so each sub-task is scored on its own."""
    req = upstream if upstream is not None else scenario.truth
    policy = get_policy(scenario.policy_version)
    now = datetime.fromisoformat(scenario.now)
    today = now.strftime("%A %d %B %Y, %H:%M")
    if subtask == "extract":
        return f"Today is {today}.\n\nTranscript:\n{scenario.transcript_text()}"
    if subtask in ("policy_check", "form_fill"):
        payload = {"now": scenario.now, "request": req,
                   "diary_that_day": _diary_for(scenario.diary, req.get("preferred_date"))}
        return f"Policy ({policy.version}):\n{policy.text}\n\nInput:\n{json.dumps(payload, sort_keys=True)}"
    if subtask == "summary":
        outcome = truth_decision(scenario, req).to_dict()
        return (f"Request:\n{json.dumps(req, sort_keys=True)}\n\nOutcome:\n{json.dumps(outcome, sort_keys=True)}"
                f"\n\nTranscript:\n{scenario.transcript_text()}")
    raise ValueError(subtask)


def truth_decision(scenario, req: dict | None = None) -> Decision:
    r = Request.from_dict(req if req is not None else scenario.truth)
    return decide(r, get_policy(scenario.policy_version), datetime.fromisoformat(scenario.now),
                  [tuple(x) for x in scenario.diary])


def truth_output(subtask: str, scenario, upstream: dict | None = None) -> dict:
    """What a perfect model would return, from the scenario truth and the policy engine."""
    if subtask == "extract":
        return dict(scenario.truth)
    d = truth_decision(scenario, upstream)
    if subtask == "policy_check":
        return {"decision": d.decision, "rule_ids": sorted(d.rule_ids), "fee_gbp": d.fee_gbp,
                "deposit_gbp": d.deposit_gbp, "reason": f"Rules applied: {', '.join(d.rule_ids) or 'none'}."}
    if subtask == "form_fill":
        return {"action": d.action, "treatment": d.treatment, "start": d.start, "duration_min": d.duration_min,
                "price_gbp": d.price_gbp, "deposit_gbp": d.deposit_gbp, "fee_gbp": d.fee_gbp,
                "guardian_required": d.guardian_required}
    if subtask == "summary":
        t = scenario.truth
        bits = [f"{t.get('patient_name')} called ({t.get('intent')})."]
        if d.start:
            bits.append(f"Outcome {d.disposition}: {d.treatment} at {d.start}.")
        else:
            bits.append(f"Outcome {d.disposition}.")
        return {"disposition": d.disposition, "summary": " ".join(bits), "follow_ups": []}
    raise ValueError(subtask)


def parse_json(text: str) -> dict | None:
    if text is None:
        return None
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None


# ---- Scoring: which fields must match the truth exactly -------------------------------------------
KEY_FIELDS = {
    "extract": ["intent", "treatment", "preferred_date", "preferred_time", "is_new_patient", "guardian_name",
                "red_flags", "existing_appointment"],
    "policy_check": ["decision", "rule_ids", "fee_gbp", "deposit_gbp"],
    "form_fill": ["action", "treatment", "start", "duration_min", "price_gbp", "deposit_gbp", "fee_gbp",
                  "guardian_required"],
    "summary": ["disposition"],
}


def _norm(field: str, v):
    if field in ("rule_ids", "red_flags"):
        return sorted(v or [])
    if isinstance(v, str):
        v = v.strip()
        if field in ("guardian_name", "patient_name"):
            return v.lower() or None
        return v or None
    if field in ("fee_gbp", "deposit_gbp", "price_gbp"):
        return int(v or 0)
    if field in ("is_new_patient", "guardian_required"):
        return bool(v)
    return v


@dataclass
class Score:
    passed: bool
    wrong_fields: list
    note: str = ""


def score(subtask: str, output: dict | None, truth: dict, claim_check: Callable[[str, dict], bool] | None = None) -> Score:
    if output is None:
        return Score(False, ["<malformed>"], "not valid JSON")
    wrong = [f for f in KEY_FIELDS[subtask] if _norm(f, output.get(f)) != _norm(f, truth.get(f))]
    note = ""
    if subtask == "summary" and not wrong and claim_check is not None:
        if not claim_check(output.get("summary", ""), truth):
            wrong.append("summary_claims")
            note = "summary makes a claim the evidence does not support"
    return Score(not wrong, wrong, note)


# ---- Corrections: the verifier's findings, written as the next user turn ----------------------------
def correction_source(subtask: str, policy_version: str) -> str:
    """Where the corrected values come from. Downstream sub-tasks are computed by the deterministic
    policy engine; extraction is checked against the call card (what the caller actually asked for)."""
    if subtask == "extract":
        return "call card"
    return f"policy engine {policy_version}"


def correction_note(subtask: str, output: dict | None, truth: dict, wrong_fields: list, policy_version: str) -> str:
    """User message that tells the model which fields its last reply got wrong and what the checker
    says they should be. It names the source, so the kept conversation is an honest correction."""
    src = correction_source(subtask, policy_version)
    if output is None or "<malformed>" in wrong_fields:
        lines = ["- the reply was not one valid JSON object"]
        wrong_fields = [f for f in KEY_FIELDS[subtask]]
    else:
        lines = []
    for f in wrong_fields:
        if f == "summary_claims":
            lines.append("- summary: it states a time, date, price or name that is not in the request or the outcome; "
                         "state only what is there")
            continue
        if f.startswith("<"):
            continue
        got = None if output is None else output.get(f)
        lines.append(f"- {f}: you gave {json.dumps(got)}; the {src} gives {json.dumps(truth.get(f))}")
    return ("Correction from the practice's checker (" + src + "). Your last reply was wrong:\n" + "\n".join(lines)
            + "\nReply again with the whole corrected JSON object, following the instructions. "
              "Change only what the checker found; keep every other field as the instructions require.")
