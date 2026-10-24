"""Runs one call's sub-tasks through both lanes, verifies each output, keeps only verified teacher
replies as Mubit examples, turns frontier errors into corrections, and logs disagreements."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import Settings
from .costs import pence
from .llm import Call, LLMResult
from .store import Store
from .subtasks import (INSTRUCTIONS, SUBTASKS, build_input, correction_note, correction_source, parse_json, score,
                       truth_output)
from . import gate


class KeepCapReached(RuntimeError):
    """Raised instead of sending a record=full call once SHADOWCALL_KEEP_CAP is reached."""


@dataclass
class SubtaskOutcome:
    subtask: str
    served_by: str
    output: dict | None
    passed: bool
    teacher_ok: bool
    shadow_ok: bool | None
    corrected: bool = False
    pence_teacher: float = 0.0
    pence_shadow: float = 0.0
    latency_teacher: float = 0.0
    latency_shadow: float = 0.0


@dataclass
class CallOutcome:
    scenario_id: str
    subtasks: list = field(default_factory=list)


class Pipeline:
    def __init__(self, s: Settings, store: Store, lanes: dict, claim_check, shadow_lane: str = "shadow"):
        self.s, self.store, self.lanes, self.claim_check = s, store, lanes, claim_check
        self.shadow_lane = shadow_lane if shadow_lane in lanes else "shadow"

    # -- one model call, scored ----------------------------------------------------------------
    def _run(self, lane: str, subtask: str, sc, upstream, record: str, temperature: float, seed: int, phase: str,
             served: bool = False, kept: bool = False, extra: dict | None = None, correction: tuple | None = None):
        """correction=(bad_reply_text, note): send a correction turn, i.e. the original request, the
        model's own wrong reply, then the checker's findings as the final user message."""
        user = build_input(subtask, sc, upstream)
        history = None
        if correction is not None:
            history = [{"role": "user", "content": user}, {"role": "assistant", "content": correction[0]}]
            user = correction[1]
        call = Call(lane=lane, subtask=subtask, system=INSTRUCTIONS[subtask], user=user, session_id=sc.session_id,
                    record=record, temperature=temperature, seed=seed, scenario=sc, upstream=upstream, extra=extra,
                    history=history)
        res: LLMResult = self.lanes[lane].complete(call)
        out = parse_json(res.text)
        truth = truth_output(subtask, sc, upstream)
        sc_ = score(subtask, out, truth, self._claims(sc, upstream))
        self.store.insert("runs", scenario_id=sc.id, session_id=sc.session_id, split=sc.split,
                          policy_version=sc.policy_version, subtask=subtask, lane=lane, phase=phase, output=out,
                          passed=int(sc_.passed), wrong=sc_.wrong_fields, tokens_in=res.tokens_in,
                          tokens_out=res.tokens_out, latency_ms=res.latency_ms, request_id=res.request_id,
                          record=record, kept=int(kept), served=int(served), tags=sc.tags)
        return out, sc_, res, truth

    def _claims(self, sc, upstream):
        evidence = build_input("summary", sc, upstream)
        return lambda summary, _truth: self.claim_check(summary, evidence)

    # -- teacher lane with verified keeping ------------------------------------------------------
    def teacher(self, subtask: str, sc, upstream=None, phase: str = "train"):
        """Held-out calls are never kept (record=metadata). Training calls: probe without keeping,
        verify, then replay to keep it. If the probe is wrong, that is a correction:
          1. correction turn: the same task gets the frontier's own reply and the checker's findings
             (policy engine or call card) as a second user turn; a verified answer is replayed with
             record=full, so Mubit keeps the whole correction conversation;
          2. optional plain resamples (off by default: live runs never fixed anything this way);
          3. otherwise the deterministic repair (engine/card output) waits for a person in the
             Fix queue. Mubit has no API to take a corrected reply, so that one stays local."""
        heldout = sc.split == "heldout"
        if heldout or not self.s.verified_keep:
            record = "metadata" if heldout else "full"
            out, s_, res, truth = self._run("teacher", subtask, sc, upstream, record, 0.0, 0, phase, kept=not heldout)
            return out, s_, res, False
        out, s_, res, truth = self._run("teacher", subtask, sc, upstream, "metadata", 0.0, 0, phase)
        if s_.passed:
            self._keep(subtask, sc, upstream, 0.0, 0)
            return out, s_, res, False
        bad_text = res.text if res.text else json.dumps(out)
        note = correction_note(subtask, out, truth, s_.wrong_fields, sc.policy_version)
        source = correction_source(subtask, sc.policy_version)
        if self.s.correction_mode == "turn":
            o2, s2, r2, _ = self._run("teacher", subtask, sc, upstream, "metadata", 0.0, 0, "correct",
                                      correction=(bad_text, note))
            if s2.passed:
                kept_ok, rid = self._keep(subtask, sc, upstream, 0.0, 0, correction=(bad_text, note))
                self.store.insert("corrections", scenario_id=sc.id, subtask=subtask, policy_version=sc.policy_version,
                                  bad=out, fixed=o2, attempts=1,
                                  status="kept_correction_turn" if kept_ok else "correction_turn_replay_failed",
                                  request_id=rid, tags=sc.tags, note=note, source=source,
                                  request=build_input(subtask, sc, upstream))
                return out, s_, res, True
        for k in range(1, self.s.max_resamples + 1):
            ex = self._resample_extra(k)
            o2, s2, r2, _ = self._run("teacher", subtask, sc, upstream, "metadata", 0.7, k, "resample", extra=ex)
            if s2.passed:
                kept_ok, rid = self._keep(subtask, sc, upstream, 0.7, k, ex)
                self.store.insert("corrections", scenario_id=sc.id, subtask=subtask, policy_version=sc.policy_version,
                                  bad=out, fixed=o2, attempts=k, status="kept_verified_resample",
                                  request_id=rid, tags=sc.tags, note=note, source=source,
                                  request=build_input(subtask, sc, upstream))
                return out, s_, res, True
        # Deterministic repair: the checker's own output. Never sent to Mubit; a person approves it.
        self.store.insert("corrections", scenario_id=sc.id, subtask=subtask, policy_version=sc.policy_version,
                          bad=out, fixed=truth, attempts=self.s.max_resamples + (self.s.correction_mode == "turn"),
                          status="needs_human", request_id=res.request_id, tags=sc.tags, note=note, source=source,
                          request=build_input(subtask, sc, upstream))
        return out, s_, res, True

    def _resample_extra(self, k: int) -> dict | None:
        if not self.s.live or self.s.teacher_send_temperature or not self.s.teacher_resample_efforts:
            return None
        efforts = self.s.teacher_resample_efforts
        return {"reasoning_effort": efforts[min(k - 1, len(efforts) - 1)].strip()}

    def _keep(self, subtask, sc, upstream, temperature, seed, extra=None, correction=None):
        """Replay a verified request with record=full so Mubit records it as a candidate kept example.
        Replays aren't guaranteed to be identical, so the reply is verified again; a failure is logged
        so a person can rate that request Bad in the console (Requests > Rate this reply)."""
        if self.s.keep_cap and self.store.query(
                "SELECT COUNT(*) n FROM runs WHERE subtask=? AND kept=1", subtask)[0]["n"] >= self.s.keep_cap:
            raise KeepCapReached(f"{subtask}: keep cap {self.s.keep_cap} reached; not sending record=full")
        o, s_, r, _ = self._run("teacher", subtask, sc, upstream, "full", temperature, seed,
                                "keep_correction" if correction else "keep", kept=True, extra=extra,
                                correction=correction)
        if not s_.passed:
            self.store.insert("corrections", scenario_id=sc.id, subtask=subtask, policy_version=sc.policy_version,
                              bad=o, fixed=None, attempts=0, status="kept_unverified_rate_bad",
                              request_id=r.request_id, tags=sc.tags)
        return s_.passed, r.request_id

    def _audit(self, key: str) -> bool:
        import hashlib
        h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        return h < self.s.audit_rate

    # -- a full call -----------------------------------------------------------------------------
    def run_call(self, sc, phase: str = "live", chain: bool = False) -> CallOutcome:
        """phase='train' builds Mubit examples; 'eval' scores held-out; 'live' serves per the gate.
        chain=False feeds each sub-task the true upstream request (teacher forcing) so each sub-task
        is scored on its own; chain=True feeds the served extraction downstream, as in production."""
        result = CallOutcome(sc.id)
        upstream = None
        for st in SUBTASKS:
            up = upstream if (chain and st != "extract") else None
            if phase == "live":
                gate.check_rollback(self.store, self.s, st, sc.policy_version)
            g = self.store.gate_state(st)
            serve_small = phase == "live" and g["state"] == "switched"
            if serve_small and not self._audit(sc.id):
                # Switched and not sampled for audit: the small model serves alone.
                sh_out, sh_s, sh_res, truth = self._run(self.shadow_lane, st, sc, up, "metadata", 0.0, 0, phase,
                                                        served=True)
                result.subtasks.append(SubtaskOutcome(st, self.shadow_lane, sh_out, sh_s.passed, False, sh_s.passed,
                                                      pence_shadow=pence(self.s, "shadow", sh_res.tokens_in, sh_res.tokens_out),
                                                      latency_shadow=sh_res.latency_ms))
                if st == "extract":
                    upstream = sh_out if isinstance(sh_out, dict) else {}
                continue
            t_out, t_s, t_res, corrected = self.teacher(st, sc, up, phase)
            if phase == "train":  # building examples only: no shadow call needed
                result.subtasks.append(SubtaskOutcome(st, "teacher", t_out, t_s.passed, t_s.passed, None, corrected,
                                                      pence(self.s, "teacher", t_res.tokens_in, t_res.tokens_out)))
                if st == "extract":
                    upstream = t_out if isinstance(t_out, dict) else {}
                continue
            sh_out, sh_s, sh_res, truth = self._run(self.shadow_lane, st, sc, up, "metadata", 0.0, 0,
                                                    phase, served=serve_small)
            if t_s.passed != sh_s.passed or json.dumps(t_out, sort_keys=True) != json.dumps(sh_out, sort_keys=True):
                who = "both_wrong" if not (t_s.passed or sh_s.passed) else (
                    "teacher" if t_s.passed and not sh_s.passed else "shadow" if sh_s.passed and not t_s.passed else "both_ok")
                self.store.insert("disagreements", scenario_id=sc.id, subtask=st, policy_version=sc.policy_version,
                                  teacher=t_out, shadow=sh_out, truth=truth, teacher_ok=int(t_s.passed),
                                  shadow_ok=int(sh_s.passed), who_right=who, tags=sc.tags)
            served_out, served_ok = (sh_out, sh_s.passed) if serve_small else (t_out, t_s.passed)
            result.subtasks.append(SubtaskOutcome(
                st, self.shadow_lane if serve_small else "teacher", served_out, served_ok, t_s.passed, sh_s.passed,
                corrected, pence(self.s, "teacher", t_res.tokens_in, t_res.tokens_out),
                pence(self.s, "shadow", sh_res.tokens_in, sh_res.tokens_out), t_res.latency_ms, sh_res.latency_ms))
            if st == "extract":
                upstream = served_out if isinstance(served_out, dict) else {}
        return result
