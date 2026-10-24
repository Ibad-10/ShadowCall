# ShadowCall: design spec

Status: draft v1, Sat 24 Oct 2026, 03:00 BST. Author: Grok Bot for Ibad. Read it alongside grill.md, which has the evidence and citations.

## 1. Problem

A business's voice agent makes several frontier-model calls on every phone call: understand the caller, check policy, fill the booking form, write the wrap-up.

That costs pence per call. Nobody checks whether those calls are correct against the business's own rules.

Mubit can learn small adapters per task, but it scores them by how closely they match the frontier ("tested against your provider model's answers", DOCS 13). Used naively, that copies the frontier's mistakes into the adapter.

## 2. Goal

Show, on a real ElevenLabs call and on a held-out synthetic set:
1. Each of four sub-tasks can be learnt by a small model through Mubit.
2. Training data is kept only when the company's policy verifier passes it. Frontier errors become corrections.
3. A sub-task switches to the small model only after it beats or matches the frontier on held-out calls, scored by the verifier. It never switches with a red-flag miss.
4. A policy change rolls back the switched sub-tasks, and they re-qualify ("fast refresh").
5. All of it is visible on one dashboard, with pence per call.

**Tracks:**
- Recurring tasks (primary).
- Fast refresh (secondary, the policy change).

## 3. Non-goals

- Replacing the live conversational reply.
- Real patient data.
- Clinical advice.
- More than one practice.
- Claims based on mock-mode numbers.

## 4. Users

| User | What they need |
|---|---|
| Practice manager | Fewer booking errors, lower cost |
| The voice-agent builder | A safe way to swap models, one sub-task at a time |
| Judges | To see a correction become a model update |

## 5. Approaches considered

| Approach | For | Against | Verdict |
|---|---|---|---|
| A. Fine-tune the whole conversation | One model | Latency; can't verify free conversation; loses Mubit's per-task design | No |
| B. **Shadow per sub-task, with a verifier-gated promotion** | Verifiable; fits Mubit's task model; safe | Needs four tasks; training limits | **Chosen** |
| C. Memory/lessons layer (old SDK) | Mubit's demos already do it | Not the current product; no novelty | No |

## 6. Architecture

```
Caller ─ ElevenLabs Agent ─(custom LLM, SSE)─► ShadowCall relay /v1/chat/completions ─► Mubit /openai/v1 ─► frontier
                         └(post-call webhook)─► ShadowCall /webhook/elevenlabs/post-call
                                                     │  (transcript + chosen call card's truth)
                                                     ▼
                       ┌──────────────── pipeline.run_call ────────────────┐
  for st in [extract, policy_check, form_fill, summary]:
     teacher lane (Mubit /openai/v1, model TEACHER_MODEL)
        train split : probe(record=metadata) → verify → keep-replay(record=full, same seed)
                      wrong → correction turn on the same task: [request, wrong reply, checker findings]
                              → verified → keep-replay of that conversation (record=full) → corrections table
                      still wrong → checker's repair → Fix queue (a person approves; local only, exportable)
        held-out    : record=metadata only (never kept)
     small lane: adapter (if callable) | open base model via Mubit /compat/{svc}/v1, record=metadata
     verifier: engine/truth (+ rule claim check, + Sapling on summary claims)
     disagreements table ← (teacher, small, truth, who_right)
     gate: shadow | switched | rolled_back → who serves; 20% audit after switching
                       └────────────────────────────────────────────────────┘
  SQLite store ─► FastAPI dashboard (/), /api/*
  eval harness (held-out, arms A–D) ─► data/eval_report.{md,json} ─► gate.try_promote
```

## 7. Components and interfaces (as built)

| Module | Responsibility | Key interface |
|---|---|---|
| `policy/engine.py` | Rules R1–R8 for v1 and v2: the ground truth | `decide(Request, Policy, now, diary) -> Decision` |
| `synth.py` | Call cards with truth, tags and a session split | `generate(n, seed, policy) -> [Scenario]` |
| `subtasks.py` | Frozen instructions, input builders, truth, scoring | `build_input`, `truth_output`, `score -> Score` |
| `llm.py` | `MubitClient` (OpenAI-compatible, env key, record header, session ID) and `MockLLM` | `complete(Call) -> LLMResult` |
| `verify.py` | Rule claim check; `SaplingClient` (only `supported` passes) | `make_claim_checker(settings)` |
| `pipeline.py` | Teacher lane with verified keeping and corrections; small lane; disagreements; serving | `Pipeline.run_call(sc, phase, chain)` |
| `gate.py` | Promotion and rollback per sub-task | `evaluate`, `try_promote`, `check_rollback` |
| `evalh.py` | Held-out arms A–D; Try models import; pipeline factory | `run_eval`, `import_tryouts`, `make_pipeline` |
| `voice.py` | ElevenLabs relay and post-call parsing | `/v1/chat/completions`, `clean_body` |
| `app.py` | Dashboard and APIs | see the README |

**The sub-task contract.** The system prompt in `INSTRUCTIONS[st]` is frozen, and `response_format` is `json_object`. The user message carries everything that changes from call to call, including the policy text, so the policy change doesn't create a new Mubit task. This is what lets the v1 adapter go stale on v2 and then refresh.

## 8. Rules (fixture policy)

| Rule | v1 | v2 |
|---|---|---|
| R1 Opening hours | Mon–Fri 08:00–18:00, Sat 09:00–13:00 | Sat closes 12:00 |
| R2 Durations and prices | Hygiene 30 min, £75 | Hygiene 45 min, £90 |
| R3 New patients | Check-up first | Check-up first, plus a £25 deposit |
| R4 Change under 24 hours | £30 fee, must be disclosed | Same |
| R5 Red flags | Call 999 or go to A&E; never book | Same |
| R6 Under-16s | Guardian required | Same |
| R7 Booking window | Not in the past; no more than 8 weeks ahead | Same |
| R8 Diary | No clashes | Same |

## 9. Gate logic

**Promote** sub-task *st* to `switched` when all of these hold on the current policy version:
- at least `GATE_MIN_HELDOUT` (20) held-out sessions;
- small-lane accuracy ≥ frontier accuracy + `GATE_MARGIN` (0);
- zero failures on red-flag calls.

**Roll back to `shadow`** when the policy version changes.

**Mark `rolled_back`** when live verified accuracy over the last 10 served calls drops below 80%.

**Manual rollback** is a dashboard button. Every change is written to `gate_events`, with the version label.

## 10. Error handling

- A Mubit error raises with its `x-middleware-request-id` and the error code (DOCS 3279+). The CLI stops, and the store keeps the runs done so far, so you can re-run with `--limit`. [Should] Skip cards that are already done.
- Malformed JSON is scored as a failure (`<malformed>`), which matches Mubit's own `Malformed tool calls` status.
- A Sapling error or `unsure` falls back to the rule check, and is not counted as verified.
- If no adapter is callable, the gate uses the base-model lane, and the README says so.

## 11. Testing

`pytest -q`: 34 tests, offline. They cover:
- the engine rules for v1 and v2;
- generator determinism and the session split;
- frozen instructions;
- scoring;
- only verified examples are kept;
- held-out calls are never kept;
- corrections;
- the gate: promote, safety block, policy rollback, and the full fast-refresh cycle;
- arms present in the eval report;
- Try models import;
- the app's full demo flow;
- the SSE relay;
- ElevenLabs field stripping;
- MubitClient headers via `MockTransport`;
- no hardcoded keys.

## 12. Metrics to report (live only)

Per sub-task and arm, on held-out:
- accuracy;
- red-flag accuracy;
- pence per call;
- median latency.

Also:
- corrections found (frontier error rate by tag);
- kept examples;
- Mubit version results (Passed / Below target / Prompt only);
- time from policy change to a re-promoted adapter;
- gateway hop from "Where the time went".

## 13. Open questions

See needs.md, Q1–Q11.

## 14. Corrections (changed Sat 04:00 BST, after reading Mubit's docs and console)
How Mubit works is set out in `docs/mubit-how-it-works.md`. The facts that matter here:
- Mubit has no API for a corrected reply.
- Ratings can't be sent with an inference key; every `/v2/*` path returns 404.
- Kept examples come only from replies that went through the gateway and that the reviewer rated up.
- A task's identity ignores messages after the instructions, so a multi-turn conversation stays in the same task.
- The session comes from the instructions plus the first user message, so a correction lands in the same session.

The correction design:
1. **Correction turn (primary).** The frontier sees its own wrong reply and the checker's findings ("Correction from the practice's checker (policy engine v1): treatment: you gave X; the policy engine gives Y"), then answers again.
   - The probe and the correction turn are sent with `record=metadata`.
   - A verified answer is replayed with `record=full`, so the kept conversation is literally "wrong → told why → fixed".
   - Status: `kept_correction_turn`. If the replay doesn't verify, the status is `correction_turn_replay_failed`.
2. **Resamples.** These are off by default (`SHADOWCALL_MAX_RESAMPLES=0`), because live resamples fixed 0 of 27.
3. **Fix queue.** If the frontier is still wrong, the checker's repair is stored as `needs_human`.
   - A person approves it in the dashboard (`POST /api/corrections/{id}/approve`, status `human_fixed`).
   - Approved fixes are exported as chat rows (`GET /api/corrections/export`).
   - They are never sent to Mubit, because Mubit offers no way to receive them.
4. **Keep cap.** `SHADOWCALL_KEEP_CAP` stops `record=full` per sub-task, as a guard against reaching 25 by accident.

Live (data/correct_live.db): 5 of 5 frontier mistakes were fixed by one correction turn, and 1 keep was sent.
