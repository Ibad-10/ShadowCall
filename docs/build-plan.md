# ShadowCall build plan: now until code freeze

> **For agentic workers (Claude Code):** use superpowers:executing-plans. Tick the `- [ ]` boxes as you go. Run `.venv/bin/python -m pytest -q` after every code task.

**Goal:** a live, honest demo of verifier-gated, per-sub-task shadow distillation through Mubit for a dental phone agent, submitted as a video of 3 minutes or less plus a PDF deck before the freeze.

**Architecture:** see spec.md §6. The code is already scaffolded in `shadowcall/`. Mock mode passes all 34 tests.

**Stack:** Python 3.13, FastAPI, httpx, SQLite, Mubit's gateway (OpenAI-compatible), ElevenLabs Agents (custom LLM).

## Key times

London time throughout. **The clocks go back at 02:00 BST on Sunday** (02:00 BST becomes 01:00 GMT).

| When (London) | UTC | What |
|---|---|---|
| Sat 24 Oct 03:00 BST | 02:00 | Now |
| Sat 20:00 BST | 19:00 | Submissions open (/submit): MP4 or MOV video of 3 min or less, plus a PDF deck |
| **Sun 01:00 BST** | **00:00** | **Mubit's daily limits reset** (training, Try models, 3 adapter starts) |
| Sun 02:00 BST, which becomes 01:00 GMT | 01:00 | Clocks go back. The hour from 01:00 to 02:00 happens twice. |
| **Sun 05:00 GMT** | **05:00** | **Code freeze. Submit before this.** |
| Sun 05:30 GMT | 05:30 | Round 1 expo at the team table |
| Sun 12:00 GMT | 12:00 | Appeals close |
| Sun 12:30 GMT | 12:30 | Five finalists give a 5-minute stage demo (applause bonus up to 0.05) |
| Sun 13:30 GMT | 13:30 | Awards |

**Working time left is about 26 hours.** It includes two sleeps.

## Budget notes (live, Sat 03:45 BST)

- **ElevenLabs:** free tier, about 6,700 characters left, so 10–15 short calls in total. Collect all data through the text path (`cli train` / `/api/chat`). Make real calls only for one rehearsal, the video take and the expo.
- **Mubit and providers:** the two smoke runs used about 250 gateway calls, about $1.25 in Mubit runs plus about $0.35 provider. A full v1 data run (about 1,000 calls) is about $5 plus $1.50.
- **Groq starter limit** is 8,000 tokens/min. The client retries on 429.

## Global constraints

Copied from spec and CLAUDE.md:
- **Every LLM call goes through Mubit** (routing counts towards "use of Mubit").
- Keys come only from env. No mock numbers in the video or deck.
- Instructions in `subtasks.INSTRUCTIONS` stay frozen once live training starts.
- Held-out calls use `record=metadata`.
- British English.

---

## Timeline

### Block 0: Sat 03:00–04:00 BST. Ibad reviews, then sleeps
- [ ] Read grill.md's top-5 table, needs.md and this plan (15 min).
- [ ] At the venue or on Discord, queue the staff questions from needs.md (Q1–Q6) for office hours.
- [ ] **Sleep from 04:00 to 09:00 BST.**

### Block 1: Sat 09:00–10:30 BST. Live smoke test (needs the Mubit key)

**Task 1: first live call per sub-task**
- [x] Key in env; both lanes probed live (smoke runs 1–2, see `shadowcall/data/smoke_report*.txt`).
- [ ] **Ibad decides:** when to cross 25 kept examples (extract and summary are at 14 after the smoke runs; training starts automatically at 25). Also the teacher model (default `gpt-6-sol`). **Changing it later creates new Mubit tasks.** Freeze `subtasks.INSTRUCTIONS` before the full run.
- [ ] Run `cp shadowcall/.env.example shadowcall/.env`, then set `SHADOWCALL_MODE=live` (the key is already in env).
- [ ] Load the env: `cd shadowcall && set -a; source .env; set +a`.
- [ ] Run `.venv/bin/python -m shadowcall.cli gen --n 160 --seed 7 --policy v1`.
- [ ] Run `.venv/bin/python -m shadowcall.cli train --cards data/cards_v1_s7.jsonl --limit 1`.
  Expected: 1 line, no error.
- [ ] In the console: **Requests** shows the calls with `mreq_` IDs, and **Tasks** shows **4 tasks** (one per sub-task). If you see more than 4, an instruction is varying, so fix it before going on.
- [x] Compat lane checked: Groq works on the starter credit with `openai/gpt-oss-20b`, JSON mode and `reasoning_effort: low`.
- [ ] Set the price env vars from the provider price pages. Note the source URLs in the README.
- [ ] Fill in the time and commit hash in `PREREG.md`, then `git init && git add -A && git commit -m "prereg"`.

### Block 2: Sat 10:30–13:00 BST. Collect v1 examples and start training
- [ ] Run `cli train --cards data/cards_v1_s7.jsonl`. That's 118 train cards, about 1,000 gateway calls, about 20–40 min.
- [ ] Watch **Tasks**. Each sub-task should pass `25 of 25`.
- [ ] Training starts by itself when it's allowed. Note each status: `Reviewing examples` → `Training` → `Testing` (DOCS).
- [ ] If you have the second key: `cli train --cards data/cards_v1_s7.jsonl --project raw`. That's arm C, learning off.
- [ ] Office hours: ask Q1 (corrections and ratings), Q2 (calling an adapter), Q3 (limits and base model).
- [ ] **Cut-line at 13:00:** if fewer than 2 tasks are training, keep only extract and form_fill on adapters. The other two stay on the base model in shadow.

### Block 3: Sat 13:00–15:30 BST. Held-out eval and gate
- [ ] Run `cli eval --cards data/cards_v1_s7.jsonl --promote`. Live, this runs arms A and B (plus D if an adapter is callable).
- [ ] When a version shows `Passed`: in **Try models**, run the held-out cards for extract and form_fill (about 20 each; check the quota). Paste the replies into `data/tryouts_v1.jsonl` as `{"scenario_id","subtask","output"}`. Then run:
  `cli import-tryouts --cards data/cards_v1_s7.jsonl --file data/tryouts_v1.jsonl`.
- [ ] **Capture:** per sub-task, the accuracy of A, B, C and D, the corrections by tag, the Mubit version result, and pence per call.
- [ ] Take screenshots: Tasks, Adapters → History, Try models, Requests showing "Where the time went".

### Block 4: Sat 15:30–18:30 BST. Voice (needs the ElevenLabs key)
- [ ] Start the server: `cli serve`. Start the tunnel: `cloudflared tunnel --url http://localhost:8013`.
- [ ] In the ElevenLabs agent, set the custom LLM URL to `https://<tunnel>/v1` and the model to `TEACHER_MODEL`. Set the secret to `SHADOWCALL_ELEVENLABS_SECRET` and the buffer words to "One moment... ".
- [ ] Set the post-call webhook to `https://<tunnel>/webhook/elevenlabs/post-call`.
- [ ] Get the dashboard cards (`GET /api/cards`), then select one (`POST /api/demo-card/{id}`). Call the agent and read the card. **Budget: about 6,700 characters in total.** Do 2 calls here (child, red flag), and keep short agent replies (set the first message to under 15 words).
- [ ] **Capture:** the first-token latency the caller hears, Mubit's "Where the time went", and whether each sub-task passed.
- [ ] **Cut-line at 18:30:** if voice isn't working, the demo uses `/api/chat`, the text simulator. Record one ElevenLabs attempt anyway, for honesty.

### Block 5: Sat 18:30–21:00 BST. Collect v2 data, start on the submission
- [ ] Run `cli gen --n 120 --seed 21 --policy v2`.
- [ ] On the dashboard, press **Policy change → v2**. The switched sub-tasks roll back. Screenshot the gate events.
- [ ] Run `cli live --cards data/cards_v2_s21.jsonl`. This shows the stale v1 lane disagreeing on v2: the hygiene duration and the deposit.
- [ ] Run `cli train --cards data/cards_v2_s21.jsonl`. This collects v2 kept examples so training can start after the 01:00 BST reset.
- [ ] **20:00:** submissions open. Make the submission draft (title, team, links).
- [ ] Draft the deck from the outline in pitch.md.

### Block 6: Sat 21:00 – Sun 00:55 BST. Video take 1, deck v1
- [ ] Record video take 1 with the v1 results, following the 3-min script in pitch.md. Use OBS or QuickTime and export MP4. The fast-refresh segment is a placeholder for now.
- [ ] Export deck v1 as PDF.
- [ ] Rehearse the expo pitch twice.

### Block 7: Sun 01:00 BST (00:00 UTC). Reset: start v2 training
- [ ] At **01:00 BST or later**, check whether form_fill v2 training starts (the limits have reset). If it's waiting on examples, run more v2 `train`.
- [ ] Start a Try models adapter for v2 when it shows `Passed`. That's adapter start 1 of 3 for the new UTC day.
- [ ] **Sleep from about 01:15 BST to 03:00 GMT** (01:15 BST → 02:00 BST, which is 01:00 GMT → 03:00 GMT, about 2 h 45 min). Set an alarm in GMT.

### Block 8: Sun 03:00–04:30 GMT. Final numbers, final video and deck
- [ ] Get the form_fill v2 result. Import the Try models v2 replies and run `cli eval --cards data/cards_v2_s21.jsonl --promote`.
- [ ] **Capture:** the time from policy change to a re-promoted lane, plus v2 accuracy for A, B and D.
- [ ] Re-record the fast-refresh segment (30–40 s) and splice it in. The video must be **3:00 or less**.
- [ ] Update the deck numbers. Export the PDF.
- [ ] Run `pytest -q`. Commit, then tag `freeze`.

### Block 9: Sun 04:30–05:00 GMT. Submit (freeze at 05:00 GMT)
Work through the submission checklist below. **Submit by 04:45 GMT.**

### After the freeze
- **05:30 GMT:** expo. The 1–2 min pitch is in pitch.md, with the dashboard live in mock and live modes.
- **12:30 GMT:** if we're a finalist, give the 5-min stage demo in pitch.md.

---

## Demo moments and the numbers to capture

| # | Moment | Number to capture (live only) |
|---|---|---|
| M1 | A real call: "Thursday week at half two, no sorry, Wednesday" | Extract passes or fails; latency the caller hears |
| M2 | Disagreement log: the frontier missed R4's £30 fee, and the verifier flags it | Frontier error rate by tag (e.g. late-change x%) |
| M3 | **The correction becomes a model update.** Corrections count rises, Tasks shows 25/25 then `Training`, a new version `Passed` | Number of corrections in the kept set; version result |
| M4 | The gate flips extract to `switched` | Held-out A vs D accuracy, n |
| M5 | Pence per call, all-frontier vs as served | p/call both ways; % saved |
| M6 | Policy v2: automatic rollback, stale disagreements, refresh, re-promotion | Time from policy change to re-promotion; v2 accuracy |
| M7 | Red-flag call: always escalated; a single miss blocks promotion | Red-flag accuracy |

## Fallbacks

| Failure | Fallback |
|---|---|
| ElevenLabs relay or tunnel fails | Text-chat simulator (`/api/chat`) on the dashboard, plus a recorded call if any worked |
| No callable adapter | Base-model lane (live through Mubit compat) for serving, plus Try models import for adapter numbers |
| Training doesn't finish before 03:30 GMT | Show v1 adapter results, plus the v2 rollback and base-model lane. Say "v2 adapter queued". |
| Mubit gateway outage | Mock mode with "SIMULATED" on screen, plus a pre-recorded video |
| Sapling unavailable | Rule-based claim check only, stated on the slide |

## Submission checklist (before 04:45 GMT)

- [ ] The video is MP4 or MOV and **3:00 or less**. Audio is clear. The first 20 s state the problem. It shows the Mubit console (Tasks, Adapters, Try models, Requests).
- [ ] The deck PDF has these slides: problem, how it works, Mubit use, results table (live numbers with n), ablation A–D, fast refresh, honesty (never-claim list), team.
- [ ] Repo link. The README says how to run in mock mode. Include PREREG.md with its timestamp, and CLAUDE.md.
- [ ] Every LLM call goes through Mubit. List the routes in the README.
- [ ] No keys in the repo (`pytest` checks this; also run `git log -p | grep -i key`).
- [ ] Mock numbers don't appear anywhere in the video or deck.
- [ ] Tracks chosen: Recurring tasks (primary), Fast refresh.
- [ ] Submitted through /submit. Screenshot the confirmation.

## Change, Sat 04:00 BST: correction turn
- [x] Read all of Mubit's docs, the old SDK and the console bundle (`docs/mubit-how-it-works.md`).
- [x] Correction turn replaces resamples. Fix queue and export are built; tests pass (43).
- [x] Live check: 5 of 5 mistakes fixed with one correction turn; 1 `record=full` keep sent.
- [ ] Ask staff Q1, Q9 and Q10 before the main data run: does the reviewer keep multi-turn rows, and is the last assistant turn what gets trained?
- [ ] For the data run, set `SHADOWCALL_KEEP_CAP` (e.g. 23) until Ibad decides to let a task reach 25.
- Note: "3 a day" is the **Try models adapter starts** limit. The training limit per day isn't published. Groq: 1,000 requests a day.
