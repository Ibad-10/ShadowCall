"""Synthetic caller-script generator for the dental booking niche.

Every scenario carries its ground truth (the request a perfect listener would extract),
so extraction is checked exactly and the policy engine gives the true decision.
The split is by session, so no held-out call shares a session with a training call.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

from .policy.engine import Request, RED_FLAGS

NOW = datetime(2026, 10, 26, 9, 0)  # Monday 26 Oct 2026, 09:00 London

FIRST = ["Aisha", "Tom", "Priya", "Jack", "Fatima", "Oliver", "Mei", "Callum", "Zainab", "Ellie", "Kwame", "Sophie",
         "Ravi", "Hannah", "Bilal", "Grace", "Dev", "Niamh", "Yusuf", "Chloe"]
LAST = ["Khan", "Smith", "Patel", "Jones", "Begum", "Williams", "Chen", "Murphy", "Okafor", "Taylor", "Ali", "Evans"]
TREAT_WORDS = {
    "checkup": ["a check-up", "a routine check", "my six-month check-up"],
    "hygiene": ["a clean with the hygienist", "a scale and polish", "hygienist appointment"],
    "filling": ["a filling", "to get a filling done", "my filling"],
    "emergency": ["an emergency appointment", "to be seen today, it's really sore"],
    "whitening_consult": ["a whitening consultation", "to ask about whitening"],
}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ORD = {1: "1st", 2: "2nd", 3: "3rd", 21: "21st", 22: "22nd", 23: "23rd", 31: "31st"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
RED_FLAG_WORDS = {
    "swelling_breathing": "my face is swollen and I'm finding it hard to breathe",
    "swelling_eye": "the swelling's gone right up to my eye",
    "uncontrolled_bleeding": "it won't stop bleeding since this morning",
    "head_injury_unconscious": "he fell off his bike, knocked his tooth out and passed out for a bit",
}


def _ord(n: int) -> str:
    return ORD.get(n, f"{n}th")


def spoken_time(h: int, m: int, rng: random.Random) -> str:
    h12 = h if h <= 12 else h - 12
    ampm = "in the morning" if h < 12 else ("in the afternoon" if h < 18 else "in the evening")
    opts = [f"{h12}:{m:02d}" + (" am" if h < 12 else " pm"), f"{h:02d}:{m:02d}"]
    if m == 30:
        opts.append(f"half {h12}" + ("" if 9 <= h <= 17 else f" {ampm}"))
    if m == 0:
        opts.append(f"{h12} o'clock {ampm}")
    if m == 15:
        opts.append(f"quarter past {h12}")
    if m == 45:
        opts.append(f"quarter to {(h12 % 12) + 1}")
    return rng.choice(opts)


def spoken_date(d: datetime, rng: random.Random) -> tuple[str, list[str]]:
    delta = (d.date() - NOW.date()).days
    tags = []
    opts = [f"the {_ord(d.day)} of {MONTHS[d.month - 1]}", f"{DAY_NAMES[d.weekday()]} the {_ord(d.day)}"]
    if delta == 1:
        opts.append("tomorrow")
    if 1 <= delta <= 6:
        opts.append(f"this {DAY_NAMES[d.weekday()]}")
    if 7 <= delta <= 13:
        # "next Sunday" is ambiguous in British English, so use the unambiguous form.
        opts.append(f"{DAY_NAMES[d.weekday()]} next week")
    if 14 <= delta <= 20 and rng.random() < 0.5:
        opts.append(f"{DAY_NAMES[d.weekday()]} week")
    s = rng.choice(opts)
    if not s.startswith("the ") and "the " not in s:
        tags.append("relative_date")
    return s, tags


@dataclass
class Scenario:
    id: str
    session_id: str
    split: str
    policy_version: str
    now: str
    diary: list
    truth: dict
    transcript: list  # [{"role": "caller"|"agent", "text": str}]
    tags: list = field(default_factory=list)

    def transcript_text(self) -> str:
        return "\n".join(f"{t['role'].upper()}: {t['text']}" for t in self.transcript)

    def request(self) -> Request:
        return Request.from_dict(self.truth)

    def to_dict(self) -> dict:
        return asdict(self)


def _split(session_id: str, heldout_frac: float) -> str:
    h = int(hashlib.sha256(session_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "heldout" if h < heldout_frac else "train"


def _diary(rng: random.Random) -> list:
    out = []
    for day in range(0, 21):
        d = NOW + timedelta(days=day)
        if d.weekday() == 6:
            continue
        for _ in range(rng.randint(1, 4)):
            h = rng.randint(8, 16)
            out.append([d.replace(hour=h, minute=rng.choice([0, 30])).strftime("%Y-%m-%dT%H:%M"), 30])
    return out


def make_scenario(i: int, rng: random.Random, policy_version: str = "v1", heldout_frac: float = 0.3) -> Scenario:
    sid = f"call-{policy_version}-{i:04d}-{rng.randint(1000, 9999)}"
    first, last = rng.choice(FIRST), rng.choice(LAST)
    name = f"{first} {last}"
    roll = rng.random()
    tags: list[str] = []
    intent = "book"
    if roll < 0.08:
        intent = "emergency"
    elif roll < 0.18:
        intent = "cancel"
    elif roll < 0.32:
        intent = "reschedule"
    elif roll < 0.38:
        intent = "enquiry"
    treatment = rng.choice(["checkup", "hygiene", "filling", "whitening_consult", "checkup", "hygiene"])
    if intent == "emergency":
        treatment = "emergency"
    is_new = rng.random() < 0.3 and intent == "book"
    child = rng.random() < 0.2
    age = rng.randint(4, 15) if child else rng.randint(16, 80)
    guardian = None
    day = NOW + timedelta(days=rng.randint(1, 20))
    if rng.random() < 0.15:
        day = NOW + timedelta(days=(5 - NOW.weekday()) % 7 + 7 * rng.randint(0, 2))  # a Saturday
        tags.append("saturday")
    hour = rng.randint(8, 17)
    if "saturday" in tags:
        hour = rng.choice([9, 10, 11, 12])
    minute = rng.choice([0, 15, 30, 45])
    slot = day.replace(hour=hour, minute=minute)
    red = []
    if intent == "emergency" and rng.random() < 0.5:
        red = [rng.choice(RED_FLAGS)]
        tags.append("red_flag")
    existing = None
    if intent in ("cancel", "reschedule"):
        late = rng.random() < 0.4
        e = (NOW + timedelta(hours=rng.randint(3, 8) if late else rng.randint(30, 200))).replace(minute=0)
        if not 8 <= e.hour <= 16:  # existing appointments sit inside opening hours
            e = e.replace(hour=8 + e.hour % 9)
        existing = e.strftime("%Y-%m-%dT%H:%M")
        if late:
            tags.append("late_change")

    turns = [{"role": "agent", "text": "Riverside Dental, you're speaking to the virtual receptionist. How can I help?"}]
    patient_desc = name
    if child:
        guardian = f"{rng.choice(FIRST)} {last}"
        tags.append("child")
        kid = rng.choice(["son", "daughter"])
        patient_desc = f"my {kid} {first}, {'he' if kid == 'son' else 'she'}'s {age}"
        turns.append({"role": "caller", "text": f"Hi, it's {guardian}, I'm calling about {patient_desc}."})
    else:
        turns.append({"role": "caller", "text": f"Hiya, my name's {name}."})
    if intent == "enquiry":
        turns.append({"role": "caller", "text": f"I just wanted to ask how much {rng.choice(TREAT_WORDS[treatment])} costs."})
    elif intent == "emergency":
        msg = RED_FLAG_WORDS[red[0]] if red else "I've got really bad toothache"
        turns.append({"role": "caller", "text": f"I need {rng.choice(TREAT_WORDS['emergency'])}, {msg}. Can someone see me today?"})
    elif intent == "cancel":
        e = datetime.fromisoformat(existing)
        turns.append({"role": "caller", "text": f"I need to cancel my appointment on {DAY_NAMES[e.weekday()]} at {spoken_time(e.hour, 0, rng)}."})
    else:
        if intent == "reschedule":
            e = datetime.fromisoformat(existing)
            turns.append({"role": "caller", "text": f"I've got {rng.choice(TREAT_WORDS[treatment])} booked {DAY_NAMES[e.weekday()]} at {spoken_time(e.hour, 0, rng)} and I need to move it."})
        else:
            if is_new:
                turns.append({"role": "caller", "text": "I'm not registered with you yet, I've just moved to the area."})
                tags.append("new_patient")
            turns.append({"role": "caller", "text": f"I'd like to book {rng.choice(TREAT_WORDS[treatment])}."})
        ds, dtags = spoken_date(slot, rng)
        tags += dtags
        ts = spoken_time(slot.hour, slot.minute, rng)
        if rng.random() < 0.2:
            wrong = slot - timedelta(days=1)
            ws, _ = spoken_date(wrong, rng)
            turns.append({"role": "caller", "text": f"Could I do {ws}... no sorry, actually {ds}, at {ts}?"})
            tags.append("self_correction")
        else:
            turns.append({"role": "caller", "text": f"Have you got anything {ds} at {ts}?"})
    if child:
        turns.append({"role": "agent", "text": "Will a parent or guardian be coming along?"})
        turns.append({"role": "caller", "text": f"Yes, me, {guardian}."})
    turns.append({"role": "agent", "text": "Thanks, let me check that for you."})

    truth = {
        "intent": intent, "patient_name": f"{first} {last}", "is_new_patient": is_new, "age": age,
        "treatment": treatment if intent not in ("cancel",) else None,
        "preferred_date": slot.strftime("%Y-%m-%d") if intent in ("book", "reschedule") else None,
        "preferred_time": slot.strftime("%H:%M") if intent in ("book", "reschedule") else None,
        "guardian_name": guardian, "red_flags": red, "existing_appointment": existing,
    }
    if intent == "emergency":
        truth["preferred_date"] = None if red else NOW.strftime("%Y-%m-%d")
        truth["preferred_time"] = None
    if intent == "enquiry":
        truth["age"] = age
    return Scenario(id=sid, session_id=sid, split=_split(sid, heldout_frac), policy_version=policy_version,
                    now=NOW.strftime("%Y-%m-%dT%H:%M"), diary=_diary(rng), truth=truth, transcript=turns,
                    tags=sorted(set(tags)))


def generate(n: int, seed: int = 7, policy_version: str = "v1", heldout_frac: float = 0.3) -> list[Scenario]:
    rng = random.Random(seed)
    return [make_scenario(i, rng, policy_version, heldout_frac) for i in range(n)]


def save(scenarios: list[Scenario], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for s in scenarios:
            f.write(json.dumps(s.to_dict()) + "\n")


def load(path: str) -> list[Scenario]:
    with open(path, encoding="utf-8") as f:
        return [Scenario(**json.loads(line)) for line in f if line.strip()]
