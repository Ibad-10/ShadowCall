"""LLM access. Live mode: every call goes through Mubit's gateway (OpenAI-compatible).
Mock mode: deterministic, offline stand-ins with a documented error model. Mock numbers are
NOT results; they only exercise the pipeline."""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field

import httpx

from .config import Settings


@dataclass
class LLMResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    request_id: str | None = None
    model: str = ""
    lane: str = ""


@dataclass
class Call:
    lane: str  # teacher | shadow | adapter
    subtask: str
    system: str
    user: str
    session_id: str
    record: str = "full"  # full | metadata | off  (x-middleware-record)
    temperature: float = 0.0
    seed: int | None = 0
    # Mock-only context: the scenario, so the mock can know the truth. Never sent anywhere.
    scenario: object | None = None
    upstream: dict | None = None
    extra: dict | None = None  # per-call body overrides, e.g. {"reasoning_effort": "high"}
    # Earlier turns between the instructions and the final user message, e.g. a correction turn:
    # [{"role":"user",...},{"role":"assistant",...}]. Messages after the instructions are not part
    # of Mubit's task identity, so a correction turn stays in the same task (and the same session).
    history: list | None = None

    def messages(self) -> list:
        return [{"role": "system", "content": self.system}, *(self.history or []),
                {"role": "user", "content": self.user}]


class MubitClient:
    """Thin OpenAI-compatible client pointed at Mubit. One client per lane (base URL + model)."""

    def __init__(self, base_url: str, model: str, api_key: str | None, timeout: float = 120.0, transport=None,
                 extra: dict | None = None, send_temperature: bool = True, max_tokens: int = 1500,
                 retries: int = 5, sleep=time.sleep, send_session: bool = True):
        self.send_session = send_session
        self.extra, self.send_temperature, self.max_tokens = dict(extra or {}), send_temperature, max_tokens
        self.retries, self._sleep = retries, sleep
        if not api_key:
            raise RuntimeError("MUBIT_API_KEY is not set. Use SHADOWCALL_MODE=mock to run offline.")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._key = api_key
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def complete(self, call: Call) -> LLMResult:
        body = {
            "model": self.model,
            "messages": call.messages(),
            "response_format": {"type": "json_object"},
            "max_completion_tokens": self.max_tokens,
            **self.extra,
            **(call.extra or {}),
        }
        if self.send_session:
            body["metadata"] = {"session_id": call.session_id}
        if self.send_temperature:
            body["temperature"] = call.temperature
        if call.seed is not None:
            body["seed"] = call.seed
        headers = {"Authorization": f"Bearer {self._key}", "x-middleware-record": call.record}
        for attempt in range(self.retries + 1):
            t0 = time.perf_counter()
            r = self._http.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            dt = (time.perf_counter() - t0) * 1000
            if r.status_code in (429, 503) and attempt < self.retries and r.headers.get("x-should-retry") != "false":
                try:
                    wait = float(r.headers.get("retry-after") or 0)
                except ValueError:
                    wait = 0
                self._sleep(min(max(wait, 2.0 * (attempt + 1)), 60))
                continue
            break
        if r.status_code >= 400:
            raise RuntimeError(f"Mubit {r.status_code} {r.headers.get('x-middleware-request-id')}: {r.text[:300]}")
        j = r.json()
        u = j.get("usage") or {}
        return LLMResult(text=j["choices"][0]["message"].get("content") or "", tokens_in=u.get("prompt_tokens", 0),
                         tokens_out=u.get("completion_tokens", 0), latency_ms=dt,
                         request_id=r.headers.get("x-middleware-request-id"), model=self.model, lane=call.lane)


# ---------------------------------------------------------------------------------------------
# Mock error model (offline only). Each profile has a base error rate and systematic weak spots
# keyed by scenario tags. Errors are deterministic for (profile, input, seed, temperature).
# ---------------------------------------------------------------------------------------------
PROFILES = {
    # The company's frontier model: good, but with systematic blind spots the verifier catches.
    "teacher": {"base": 0.03, "weak": {"child": 0.35, "self_correction": 0.3, "late_change": 0.25}},
    # Open base model, prompt only.
    "shadow": {"base": 0.22, "weak": {"relative_date": 0.4, "child": 0.4, "late_change": 0.4, "saturday": 0.3}},
}


@dataclass
class MockAdapterState:
    """Simulates a Mubit adapter for offline tests: it imitates what it was trained on.
    trained_on: list of (tags, was_verified, policy_version)."""
    trained_on: list = field(default_factory=list)

    def error_rate(self, tags: list, policy_version: str) -> float:
        n = len(self.trained_on)
        if n < 25:
            return 1.0  # no adapter yet
        same_policy = sum(1 for _, _, v in self.trained_on if v == policy_version)
        if same_policy < 10:
            return 0.6  # stale: trained on another policy version
        base = max(0.02, 0.15 - 0.002 * n)
        # A raw-trained adapter copies the teacher's systematic errors.
        # A raw-trained adapter learnt the teacher's blind spots along with everything else.
        raw = [t for t, verified, _ in self.trained_on if not verified]
        inherited = 0.0
        if raw:
            for tag, rate in PROFILES["teacher"]["weak"].items():
                if tag in tags and any(tag in t for t in raw):
                    inherited = max(inherited, rate * 0.8)
        return min(1.0, base + inherited)


def _rng(*parts) -> random.Random:
    h = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def corrupt(subtask: str, truth: dict, rng: random.Random, tags: list) -> dict:
    """Make one plausible mistake of the kind models make on this sub-task."""
    out = json.loads(json.dumps(truth))
    if subtask == "extract":
        choices = []
        if "child" in tags:
            choices.append(lambda o: o.update(guardian_name=None))
        if "self_correction" in tags and o_get(out, "preferred_date"):
            choices.append(lambda o: o.update(preferred_date=_shift(o["preferred_date"], -1)))
        if o_get(out, "preferred_time"):
            choices.append(lambda o: o.update(preferred_time=_shift_time(o["preferred_time"])))
        choices.append(lambda o: o.update(is_new_patient=not o.get("is_new_patient")))
        rng.choice(choices)(out)
    elif subtask == "policy_check":
        choices = [lambda o: o.update(rule_ids=[r for r in o["rule_ids"] if r != "R6"] if "R6" in o["rule_ids"] else o["rule_ids"] + ["R8"])]
        if "late_change" in tags:
            choices.append(lambda o: o.update(fee_gbp=0, rule_ids=[r for r in o["rule_ids"] if r != "R4"]))
        choices.append(lambda o: o.update(decision="allow" if o["decision"] != "allow" else "deny"))
        rng.choice(choices)(out)
    elif subtask == "form_fill":
        choices = [lambda o: o.update(guardian_required=not o["guardian_required"])]
        if out.get("duration_min"):
            choices.append(lambda o: o.update(duration_min=30 if o["duration_min"] != 30 else 45))
        if "late_change" in tags:
            choices.append(lambda o: o.update(fee_gbp=0))
        rng.choice(choices)(out)
    elif subtask == "summary":
        opts = ["booked", "no_slot", "info_only"]
        out["disposition"] = [o for o in opts if o != out["disposition"]][0]
    return out


def o_get(d, k):
    return d.get(k)


def _shift(day: str, n: int) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def _shift_time(t: str) -> str:
    h, m = map(int, t.split(":"))
    return f"{(h + 1) % 24:02d}:{m:02d}"  # off by an hour, e.g. "half two" heard as 15:30


class MockLLM:
    def __init__(self, profile: str, adapter: MockAdapterState | None = None):
        self.profile = profile
        self.adapter = adapter
        self.model = f"mock-{profile}"

    def complete(self, call: Call) -> LLMResult:
        from .subtasks import truth_output
        sc = call.scenario
        if sc is None:
            raise ValueError("MockLLM needs call.scenario")
        truth = truth_output(call.subtask, sc, call.upstream)
        tags = list(sc.tags)
        if self.adapter is not None:
            p_err = self.adapter.error_rate(tags, sc.policy_version)
        else:
            prof = PROFILES[self.profile]
            p_err = prof["base"]
            for tag, rate in prof["weak"].items():
                if tag in tags:
                    p_err = max(p_err, rate)
            if call.temperature > 0:
                p_err *= 0.6  # resampling sometimes escapes a blind spot
            if call.history:
                p_err *= 0.15  # mock assumption: told exactly which fields are wrong, a model mostly fixes them
        rng = _rng(self.profile, call.subtask, call.user, call.seed, call.temperature, call.history)
        out = corrupt(call.subtask, truth, rng, tags) if rng.random() < p_err else truth
        text = json.dumps(out)
        tin, tout = len(call.system + call.user) // 4, len(text) // 4
        lat = {"teacher": 650.0, "shadow": 180.0}.get(self.profile, 150.0) + rng.random() * 80
        rid = "mreq_mock" + hashlib.md5((call.user + str(call.seed)).encode()).hexdigest()[:24]
        return LLMResult(text=text, tokens_in=tin, tokens_out=tout, latency_ms=lat, request_id=rid,
                         model=self.model, lane=call.lane)


def make_lanes(s: Settings, adapter_state: MockAdapterState | None = None) -> dict:
    """Return {"teacher": client, "shadow": client, ["adapter": client]}."""
    if not s.live:
        lanes = {"teacher": MockLLM("teacher"), "shadow": MockLLM("shadow")}
        if adapter_state is not None:
            lanes["adapter"] = MockLLM("adapter", adapter_state)
        return lanes
    lanes = {"teacher": MubitClient(s.teacher_base_url, s.teacher_model, s.mubit_api_key, extra=s.teacher_extra,
                                    send_temperature=s.teacher_send_temperature, max_tokens=s.max_completion_tokens,
                                    send_session=s.teacher_send_session),
             "shadow": MubitClient(s.shadow_base_url, s.shadow_model, s.mubit_api_key, extra=s.shadow_extra,
                                   send_temperature=s.shadow_send_temperature, max_tokens=s.max_completion_tokens,
                                   send_session=s.shadow_send_session)}
    if s.adapter_base_url and s.adapter_model:
        lanes["adapter"] = MubitClient(s.adapter_base_url, s.adapter_model, s.mubit_api_key)
    return lanes
