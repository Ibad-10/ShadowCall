"""Deterministic policy engine: the ground truth for every encoded rule.

Given the true (or extracted) request slots, the policy version and the diary,
it returns the decision, the rules that fired and the booking that should be made.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent

TREATMENTS = ["checkup", "hygiene", "filling", "emergency", "whitening_consult"]
INTENTS = ["book", "reschedule", "cancel", "emergency", "enquiry"]
RED_FLAGS = ["swelling_breathing", "swelling_eye", "uncontrolled_bleeding", "head_injury_unconscious"]


@dataclass(frozen=True)
class Policy:
    version: str
    sat_close: int  # hour
    durations: dict
    prices: dict
    new_patient_deposit: int
    late_fee: int = 30
    weekday_open: int = 8
    weekday_close: int = 18
    sat_open: int = 9
    max_weeks_ahead: int = 8

    @property
    def text(self) -> str:
        return (HERE / f"policy_{self.version}.md").read_text(encoding="utf-8")


POLICIES = {
    "v1": Policy("v1", sat_close=13,
                 durations={"checkup": 30, "hygiene": 30, "filling": 45, "emergency": 20, "whitening_consult": 20},
                 prices={"checkup": 65, "hygiene": 75, "filling": 140, "emergency": 95, "whitening_consult": 0},
                 new_patient_deposit=0),
    "v2": Policy("v2", sat_close=12,
                 durations={"checkup": 30, "hygiene": 45, "filling": 45, "emergency": 20, "whitening_consult": 20},
                 prices={"checkup": 65, "hygiene": 90, "filling": 140, "emergency": 95, "whitening_consult": 0},
                 new_patient_deposit=25),
}


def get_policy(version: str) -> Policy:
    return POLICIES[version]


@dataclass
class Request:
    intent: str
    patient_name: str | None = None
    is_new_patient: bool = False
    age: int | None = None
    treatment: str | None = None
    preferred_date: str | None = None  # YYYY-MM-DD
    preferred_time: str | None = None  # HH:MM
    guardian_name: str | None = None
    red_flags: list = field(default_factory=list)
    existing_appointment: str | None = None  # YYYY-MM-DDTHH:MM for reschedule/cancel

    @classmethod
    def from_dict(cls, d: dict) -> "Request":
        keys = cls.__dataclass_fields__.keys()
        out = {k: d[k] for k in keys if k in d}
        out["red_flags"] = list(out.get("red_flags") or [])
        out["is_new_patient"] = bool(out.get("is_new_patient") or False)
        return cls(**out)


@dataclass
class Decision:
    decision: str  # allow | deny | escalate
    rule_ids: list
    action: str  # create | move | cancel | none | urgent_999
    treatment: str | None = None
    start: str | None = None
    duration_min: int | None = None
    price_gbp: int = 0
    deposit_gbp: int = 0
    fee_gbp: int = 0
    guardian_required: bool = False
    disposition: str = "info_only"
    alternative: str | None = None  # e.g. offer checkup instead

    def to_dict(self) -> dict:
        return asdict(self)


def _hours(p: Policy, d: date) -> tuple[int, int] | None:
    wd = d.weekday()
    if wd == 6:
        return None
    if wd == 5:
        return (p.sat_open, p.sat_close)
    return (p.weekday_open, p.weekday_close)


def fits_hours(p: Policy, start: datetime, minutes: int) -> bool:
    h = _hours(p, start.date())
    if h is None:
        return False
    end = start + timedelta(minutes=minutes)
    open_dt = start.replace(hour=h[0], minute=0)
    close_dt = start.replace(hour=h[1], minute=0)
    return open_dt <= start and end <= close_dt


def clashes(diary: list[tuple[str, int]], start: datetime, minutes: int) -> bool:
    end = start + timedelta(minutes=minutes)
    for s, m in diary:
        bs = datetime.fromisoformat(s)
        be = bs + timedelta(minutes=m)
        if start < be and bs < end:
            return True
    return False


def first_free(policy: Policy, day: str, minutes: int, now: datetime, diary) -> str | None:
    d = datetime.fromisoformat(f"{day}T00:00")
    h = _hours(policy, d.date())
    if h is None:
        return None
    t = d.replace(hour=h[0])
    while t.hour < h[1]:
        if t >= now and fits_hours(policy, t, minutes) and not clashes(diary, t, minutes):
            return t.strftime("%H:%M")
        t += timedelta(minutes=15)
    return None


def decide(req: Request, policy: Policy, now: datetime, diary: list[tuple[str, int]]) -> Decision:
    rules: list[str] = []
    # R5 first: safety beats everything.
    if req.red_flags:
        return Decision("escalate", ["R5"], "urgent_999", disposition="escalated_urgent")
    if req.intent == "enquiry":
        return Decision("allow", [], "none", disposition="info_only")
    if req.intent == "cancel":
        fee = 0
        if req.existing_appointment:
            appt = datetime.fromisoformat(req.existing_appointment)
            if appt - now < timedelta(hours=24):
                fee = policy.late_fee
                rules.append("R4")
        return Decision("allow", rules, "cancel", fee_gbp=fee, disposition="cancelled")

    treatment = req.treatment or ("emergency" if req.intent == "emergency" else "checkup")
    alternative = None
    if req.is_new_patient and treatment in ("hygiene", "filling"):
        rules.append("R3")
        alternative = "checkup"
        treatment = "checkup"
    guardian = req.age is not None and req.age < 16
    if guardian:
        rules.append("R6")
    minutes = policy.durations[treatment]
    fee = 0
    action = "create"
    if req.intent == "reschedule":
        action = "move"
        if req.existing_appointment:
            appt = datetime.fromisoformat(req.existing_appointment)
            if appt - now < timedelta(hours=24):
                fee = policy.late_fee
                rules.append("R4")
    if req.preferred_date and not req.preferred_time:
        found = first_free(policy, req.preferred_date, minutes, now, diary)
        if found:
            req = Request(**{**req.__dict__, "preferred_time": found})
    if not (req.preferred_date and req.preferred_time):
        return Decision("deny", rules + ["MISSING_SLOT"], "none", treatment=treatment, guardian_required=guardian,
                        disposition="no_slot",
                        alternative=alternative)
    start = datetime.fromisoformat(f"{req.preferred_date}T{req.preferred_time}")
    if start < now or start > now + timedelta(weeks=policy.max_weeks_ahead):
        return Decision("deny", rules + ["R7"], "none", treatment=treatment, guardian_required=guardian, disposition="no_slot",
                        alternative=alternative)
    if not fits_hours(policy, start, minutes):
        return Decision("deny", rules + ["R1"], "none", treatment=treatment, guardian_required=guardian, disposition="no_slot",
                        alternative=alternative)
    if clashes(diary, start, minutes):
        return Decision("deny", rules + ["R8"], "none", treatment=treatment, guardian_required=guardian, disposition="no_slot",
                        alternative=alternative)
    if guardian:
        if not req.guardian_name:
            return Decision("deny", rules + ["GUARDIAN_MISSING"], "none", treatment=treatment,
                            guardian_required=True, disposition="no_slot", alternative=alternative)
    deposit = policy.new_patient_deposit if req.is_new_patient else 0
    if deposit:
        rules.append("R3")
    return Decision("allow", sorted(set(rules)), action, treatment=treatment, start=start.strftime("%Y-%m-%dT%H:%M"),
                    duration_min=minutes, price_gbp=policy.prices[treatment], deposit_gbp=deposit, fee_gbp=fee,
                    guardian_required=guardian,
                    disposition="rescheduled" if action == "move" else "booked", alternative=alternative)
