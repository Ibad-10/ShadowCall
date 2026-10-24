# CLAUDE.md — ShadowCall (Mubit Night Shift hackathon)

## Brief
Shadow mode for a voice agent. A UK dental practice's ElevenLabs phone agent keeps running on its frontier model through Mubit's gateway. Mubit learns a small open-model adapter for each of four sub-tasks: extract, policy_check, form_fill and summary. A sub-task switches to the small model only after it passes a held-out test scored by the practice's policy rules, never by the frontier's answers. Frontier errors caught by the verifier become corrections. A policy change (v1 → v2) triggers a rollback and a fast refresh. Judging: Mubit use (a correction visibly becoming a model update), usefulness, technical execution and demo, each 25%.

**Code freeze: Sun 25 Oct 2026, 05:00 GMT** (clocks go back 02:00 BST → 01:00 GMT that night, so this is 05:00 London). Submissions open Sat 24 Oct 20:00 BST via /submit: MP4/MOV demo video ≤3 min + PDF deck. Expo from 05:30 GMT; 5 finalists stage demo 12:30 GMT. Mubit daily limits reset 00:00 UTC = Sun 01:00 BST. Plan: docs/build-plan.md; pitch: docs/pitch.md.

## Hard rules
- **Every LLM call goes through Mubit.**
  - Teacher: `https://api.mubit.ai/openai/v1`.
  - Open model: `https://api.mubit.ai/compat/{groq|together|openrouter|mistral}/v1`.
  - No direct provider calls. Sapling is a verifier, not an LLM call, but confirm the rule with Mubit staff (see ../needs.md).
- Keys come only from env (`MUBIT_API_KEY`, `MUBIT_API_KEY_RAW`, `BANYAN_API_KEY`, `SHADOWCALL_ELEVENLABS_SECRET`). Never hardcode them, log them or commit `.env`. A pure-Python test scans for key patterns.
- **Instructions (system prompts) in `subtasks.INSTRUCTIONS` are frozen.** Mubit defines a task by its instructions, tools, tool choice, output format and model. Changing any one of them starts a new task and resets the count towards 25. Anything that varies per call, including the policy text, goes in the user message.
- **Held-out calls are sent with `x-middleware-record: metadata` and are never kept.** Split by session (`synth._split`). Use `metadata.session_id` on every call.
- **Mock mode** (`SHADOWCALL_MODE=mock`) must keep working offline, and `pytest -q` must pass with no keys. Never present mock numbers as results. The UI and the report label them.
- **The verifier is authoritative.** Never score a lane by agreement with the frontier.
- British English in the UI and docs.
- Mubit limits: about 25 kept examples before the first training; a daily training limit plus a pause between trainings; 3 adapter starts per organisation per UTC day. The reset is 00:00 UTC, which is 01:00 BST on Sun 25 Oct, just before the clocks go back. Try models calls are "not stored · trains nothing". There is no adapter model ID.

## Architecture
```
ElevenLabs ──SSE──> voice.py /v1/chat/completions ──> Mubit /openai/v1 (frontier, live answer)
           └─post-call webhook──> app.py ──> pipeline.run_call(card with real transcript)
pipeline: for each sub-task
   teacher lane: probe (record=metadata) → verify → keep-replay (record=full, same seed)
                 wrong → correction turn (wrong reply + checker findings) → verified → keep that conversation
                 still wrong → needs_human (Fix queue; approve + export; never sent to Mubit)
   small lane:   Mubit compat open model (prompt-only) | adapter (if callable) → verify
   disagreements table (who was right, by verifier) · gate.py decides who serves
eval: evalh.run_eval on held-out: A frontier, B open base, C adapter raw, D adapter verified
```

## Web app
- `app.py` serves `static/{landing,login,signup,app}.html` via `page()` (UTF-8, `text/html; charset=utf-8`). `/app/*` is one console page; `static/js/app.js` routes client-side.
- `auth.py`: Argon2id, hashed session tokens, CSRF header on writes, Origin check, throttle. Demo account only from `DEMO_USER`/`DEMO_PASSWORD`.
- CSP forbids inline scripts: put JS in `static/js/`. Always pass `encoding="utf-8"` to every text read/write (Windows defaults to cp1252; that broke the mock RNG seeds and the gate test).
- Design rules: `DESIGN.md`. Tests sign in via `tests/helpers.signed_in()`.

## Commands
```
.venv/bin/python -m pytest -q
SHADOWCALL_MODE=mock .venv/bin/python -m shadowcall.cli serve
python -m shadowcall.cli gen|train|eval|live|status ...
```

## Env vars
See `.env.example`. The key ones:
- `SHADOWCALL_MODE`
- `MUBIT_API_KEY`
- `MUBIT_API_KEY_RAW`
- `TEACHER_MODEL`
- `SHADOW_MODEL`
- `MUBIT_SHADOW_BASE_URL`
- `MUBIT_ADAPTER_BASE_URL` / `MUBIT_ADAPTER_MODEL`
- `BANYAN_API_URL`
- `SHADOWCALL_ELEVENLABS_SECRET`
- `SHADOWCALL_BUFFER_WORDS`
- `SHADOWCALL_CORRECTION` (`turn`/`off`)
- `SHADOWCALL_MAX_RESAMPLES` (default 0)
- `SHADOWCALL_KEEP_CAP` (stop `record=full` per sub-task; use it to stay under 25)
- the price vars

## Todo (in order; see docs/build-plan.md)
1. [ ] Smoke test live mode. Run one call per sub-task with a real key, check `x-middleware-request-id`, then check the console's Requests and Tasks pages: there should be 4 tasks.
2. [ ] Check `SHADOW_MODEL` on the compat service with `GET /compat/groq/v1/models`. Confirm `response_format: json_object` works there; if it doesn't, drop it on that lane.
3. [ ] Run `train` live on v1. Watch Tasks reach 25 kept examples per sub-task. Start training (limit: 3 starts a day).
4. [ ] Write PREREG.md and commit it before the first training call.
5. [ ] Run the learning-off project with `train --project raw` (second Mubit project key).
6. [ ] Get adapter outputs on held-out: through a callable adapter (`MUBIT_ADAPTER_*`) if staff expose one, otherwise copy Try models replies into a JSONL and run `cli import-tryouts --cards ... --file ...` (already built).
7. [ ] Hook up the ElevenLabs agent and post-call webhook. Run 3 real calls from cards.
8. [ ] Run the v2 fast-refresh cycle live.
9. [ ] Record a backup video of the demo. Write the submission.
10. [ ] Stretch: Sapling endpoint for summary claims; check the ElevenLabs webhook HMAC; an audit-sample chart.

## Mubit facts (see docs/mubit-how-it-works.md)
- **Never cross 25 kept examples on any task without Ibad's say-so.** Training starts by itself. Set `SHADOWCALL_KEEP_CAP`.
- There is no adapter model ID and no ratings API for inference keys (`/v2/*` returns 404). The old SDK's outcome and feedback calls are memory-engine only.
