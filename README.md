# ShadowCall

**A dental practice's phone agent keeps running on its frontier model. Behind it, Mubit learns a small open-model adapter for each sub-task of the call. A sub-task switches to its adapter only after the adapter beats the frontier on held-out calls, checked by the practice's own policy rules rather than by the frontier.**

Built for Mubit's Night Shift hackathon (23–25 Oct 2026). All code was written during the event.

## What it does

1. **Shadow mode.** Live calls come in through ElevenLabs. The company's frontier model answers them through Mubit's gateway, exactly as it does today.
2. **Four sub-tasks per call.** Each has fixed instructions, so Mubit treats each one as its own task:
   - `extract`: intent and slots, such as the date, time, treatment, new patient, child and red flags;
   - `policy_check`: the decision and which rules apply;
   - `form_fill`: the booking record;
   - `summary`: the after-call wrap-up.
3. **A verifier that isn't the model.** A deterministic policy engine is the ground truth, built from the practice's policy (`policy/policy_v1.md`, `policy_v2.md`). Banyan Sapling checks the claims in the summary when it's available.
4. **Mubit keeps only verified examples.** For each training call, the frontier's reply is first probed without being kept (`x-middleware-record: metadata`) and then verified. If it passes, the same seed is replayed with full recording, so Mubit keeps it. If it fails, that frontier error becomes a correction: the frontier is shown its wrong reply and the checker's findings in a second turn of the same task. A verified answer is replayed with full recording, so Mubit keeps the whole correction conversation. If it is still wrong, the checker's repair waits in the console's Fix queue (Corrections) for a person to approve it. Approved fixes stay local and can be exported, because Mubit has no API for corrected replies. So the adapter is trained to match a teacher whose kept answers are all correct.
5. **Promotion gate per sub-task.** A sub-task goes from `shadow` to `switched` only when, on at least 20 held-out sessions, the adapter is at least as accurate as the frontier and misses no red-flag (999) cases. After switching, 20% of calls are still audited by the frontier.
6. **Fast refresh.** When the policy changes from v1 to v2, every switched sub-task rolls back to shadow, re-qualifies on v2 data, and switches again.
7. **Dashboard** with a disagreement log (the verifier says who was right), corrections, kept-example counts towards 25, gate events, pence per call and rollback buttons.

## Run the demo: replay the real live run (no keys, no calls)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export SHADOWCALL_MODE=replay DEMO_USER=demo@example.com DEMO_PASSWORD='pick-a-long-password'
.venv/bin/python -m shadowcall.cli serve   # http://localhost:8013
```

`SHADOWCALL_MODE=replay` is the demo default (Procfile, Dockerfile, `render.yaml`, `fly.toml`). It loads `data/live_replay.json`, the real run through Mubit on Sat 24 Oct 2026 (05:16–06:02 BST): 719 recorded replies with their Mubit request ids, scores, tokens and times, the 19 corrections and the 90 call cards. It holds no keys and no request headers. Every page is filled from it: the gate decides each job from the real held-out scores, disagreements are the real pairs where one model passed and the other failed, and the live feed replays the real calls in order, 30 times faster, on a loop (`SHADOWCALL_REPLAY_SPEED`). Replay is read-only: buttons that would make new model calls are hidden and their endpoints return 409. It writes to `data/replay.db` unless `SHADOWCALL_DB` is set, and reloads the replay on every start. To rebuild the JSON from the gitignored `data/live_run.db`: `python scripts_export_replay.py`.

## Run it offline with simulated models (mock)

```bash
.venv/bin/python -m pytest -q
export SHADOWCALL_MODE=mock DEMO_USER=demo@example.com DEMO_PASSWORD='pick-a-long-password'
.venv/bin/python -m shadowcall.cli serve   # http://localhost:8013
```

Open http://localhost:8013, sign in with the demo account (or create one), and on **Overview** press **Collect examples**, then **Run held-out eval**, then **Send live calls**. Then go to **Policy** and press **Switch to v2 and re-qualify**.

Mock mode uses simulated models and labels its numbers as **not results**.

## The web app

| Page | Route | What it shows |
|---|---|---|
| Landing | `/` | What ShadowCall does, plus this server's live numbers (`GET /api/public/metrics`, no call content) |
| Sign in / Create account | `/login`, `/signup` | Email and password |
| Overview | `/app` | Pence per call, sub-tasks switched, lane agreement, verifier pass rate, kept examples towards 25, gate activity, run buttons |
| Calls | `/app/calls`, `/app/calls/{id}` | Every call; the detail view has the transcript, each sub-task's frontier and small replies, the verifier's verdicts and what the policy engine expected |
| Try a call | `/app/try` | Call cards; pick one for the phone demo, or run typed caller lines through both lanes (the text-chat fallback) |
| Disagreements | `/app/disagreements` | Calls where only one lane passed, with both replies and the expected one |
| Corrections | `/app/corrections` | The Fix queue: approve (or edit, then approve) the repair; export fixes as JSON |
| Promotion gate | `/app/gate` | Each sub-task's state, held-out accuracy, kept examples, roll back / back to shadow |
| Policy | `/app/policy` | The v1 → v2 diff and **Fast refresh** (switch, roll back, re-collect, re-evaluate, re-gate) |
| Evaluation | `/app/evaluation` | The held-out ablation table and chart |
| Settings | `/app/settings` | Mode, models, endpoints, gate and prices. Keys show **Set / Not set** only; values never reach the browser |

Built with FastAPI plus plain HTML, CSS and JavaScript modules: no build step, no CDN, fonts and icons served locally, so it works offline at the expo. The design system is in `DESIGN.md`.

**Sign-in and security**

- Passwords are hashed with Argon2id. Sessions are random tokens in an HttpOnly, SameSite=Lax cookie (Secure over HTTPS); only a hash of the token is stored.
- Every state-changing request needs the session's CSRF token in `X-CSRF-Token`, and cross-site `Origin`s are refused. Sign-in accepts JSON only.
- Failed sign-ins are throttled (8 per 10 minutes per address and email).
- The demo account comes from `DEMO_USER` / `DEMO_PASSWORD`. Nothing is hardcoded. With neither set, there is no demo account.
- `SHADOWCALL_SIGNUP=false` makes it invite-only. `SHADOWCALL_AUTH=false` turns sign-in off (local use only).
- The ElevenLabs routes (`/v1/...`, `/webhook/...`) don't use the session; they check `SHADOWCALL_ELEVENLABS_SECRET`.
- Pages are sent as `text/html; charset=utf-8` with a strict Content-Security-Policy (no inline scripts).
- In live mode, run buttons and Fast refresh ask before sending real calls, because they cost money and can push a task towards Mubit's 25-example training trigger.

## Run it on Windows (PowerShell)

```powershell
cd D:\projects\mubit\shadowcall
py -3.12 -m venv .venv            # once
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
$env:SHADOWCALL_MODE = "replay"   # or "mock" for simulated models
$env:DEMO_USER = "demo@example.com"
$env:DEMO_PASSWORD = "pick-a-long-password"
$env:PYTHONUTF8 = "1"             # optional; the app already reads and writes UTF-8 explicitly
.venv\Scripts\python -m uvicorn shadowcall.app:app --port 8013
```

Then open http://localhost:8013. If the browser shows odd characters such as `Â·` or `â€”`, you are running an old copy: every file read now names `encoding="utf-8"`, because Windows otherwise decodes text as cp1252.

## Deploy (not done yet; nothing has been deployed)

The app is one process with a SQLite file, so give it a **persistent disk** and run one instance. Set `DEMO_USER`, `DEMO_PASSWORD` and any keys as the host's secrets, never in the repo. On the public internet, set `SHADOWCALL_SIGNUP=false` and keep `SHADOWCALL_MODE=replay` (or `mock`) unless you mean to spend.

- **Docker (anywhere):** `docker build -t shadowcall .` then `docker run -p 8000:8000 -v shadowcall-data:/data --env-file .env shadowcall`.
- **Render:** `render.yaml` is a Blueprint (Docker runtime, 1 GB disk at `/data`, health check `/healthz`). In Render choose **New → Blueprint**, pick the repo, then fill in the secret env vars it asks for.
- **Railway:** new project from the repo; it builds the `Dockerfile`. Add a volume mounted at `/data`, set `SHADOWCALL_DB=/data/shadowcall.db` and the secrets. Railway sets `PORT`.
- **Fly.io:** `fly launch --no-deploy --copy-config`, `fly volumes create shadowcall_data --size 1 --region lhr`, `fly secrets set DEMO_USER=... DEMO_PASSWORD=...`, then `fly deploy`. Config is in `fly.toml`.
- **Heroku-style hosts:** the `Procfile` runs uvicorn on `$PORT` with proxy headers on, so Secure cookies work behind the host's HTTPS.

## Run it live

```bash
cp .env.example .env    # fill in MUBIT_API_KEY etc.
set -a; source .env; set +a; export SHADOWCALL_MODE=live
python -m shadowcall.cli gen --n 160 --seed 7 --policy v1
python -m shadowcall.cli train --cards data/cards_v1_s7.jsonl          # ~118 train calls x 4 sub-tasks
python -m shadowcall.cli train --cards data/cards_v1_s7.jsonl --project raw   # learning-off arm (2nd project)
python -m shadowcall.cli eval  --cards data/cards_v1_s7.jsonl --promote
python -m shadowcall.cli serve
```

## Voice

1. Expose port 8013 with `cloudflared tunnel --url http://localhost:8013` or ngrok.
2. In ElevenLabs Agents, open **Custom LLM** and set the server URL to `https://<tunnel>/v1`, with the secret `SHADOWCALL_ELEVENLABS_SECRET`.
3. Set the post-call webhook to `https://<tunnel>/webhook/elevenlabs/post-call`.
4. Choose a call card in **Try a call** (or `POST /api/demo-card/{id}`) and read its script aloud. The real transcript is then scored against that card's truth.

**Fallback:** **Try a call → Run through both lanes** (`POST /api/chat`) is a text-chat simulator that runs a card, or your own caller lines, through both lanes.

## Layout

```
shadowcall/policy/engine.py   deterministic rules R1–R8 (v1, v2) = ground truth
shadowcall/synth.py           call-card generator with truth, hard-case tags, session split
shadowcall/subtasks.py        fixed instructions, inputs, truth, scoring
shadowcall/llm.py             Mubit client (OpenAI-compatible) + offline mock error model
shadowcall/pipeline.py        teacher lane (verified keeping + corrections), shadow lane, disagreements
shadowcall/gate.py            promotion / rollback per sub-task
shadowcall/evalh.py           held-out harness, arms A–D
shadowcall/voice.py           ElevenLabs custom-LLM SSE relay + post-call parsing
shadowcall/app.py             FastAPI: pages, sign-in guard, JSON APIs
shadowcall/auth.py            accounts (Argon2id), sessions, CSRF, demo seed
shadowcall/static/            landing/login/signup/app HTML, css/, js/ (no build step), fonts, icons
Dockerfile, render.yaml, fly.toml, Procfile   hosting (not deployed)
```


## Hackathon timeline

Code freeze **Sun 25 Oct 2026 05:00 GMT** (clocks go back at 02:00 BST). Submit via /submit (opens Sat 20:00 BST): MP4/MOV video ≤ 3 min + PDF deck. Every generative LLM call routes through Mubit: teacher via `/openai/v1`, shadow/open model via `/compat/{groq|together|openrouter|mistral}/v1`, ElevenLabs relay → Mubit. Sapling (if used) is a classifier outside the gateway — confirmed with staff: _TBD_.

## Live smoke runs (Sat 24 Oct 2026, about 03:30–03:50 BST)

`scripts_smoke.py` runs 10 cards (7 train, 3 held-out) end to end in live mode, writing to its own DB. Summarise one with `scripts_smoke_report.py data/smoke2.db`. Reports: `data/smoke_report1.txt` (before the spec fixes) and `data/smoke_report2.txt` (after). These are **10-call smoke numbers, not results.**

Run 1 exposed fixture bugs, not just model errors. Fixes:
- The v1 policy said it expired on 25 Oct.
- "9 o'clock in the afternoon" was used for 21:00.
- "Next Sunday" was ambiguous.
- `rule_ids` and `fee_gbp` were ambiguous.
- R6 was missing on refused slots.
- The claim check rejected "8:00 a.m." against "08:00".
- Teacher resamples were identical (0 of 27 fixed). They have been replaced by a correction turn, which fixed 5 of 5 live.

## Live run (Sat 24 Oct 2026, 05:16–06:02 BST)
Real Mubit calls: `gpt-6-sol` against `openai/gpt-oss-20b`, scored by our own checker. The results are in `data/live_results.md` and `.json`, and the Evaluation page shows them with the label "Live — real Mubit calls". To reproduce, run `scripts_live_run.py` with `train`, `eval --tag base` and `report`. The run log and the deviations from the plan are in `PREREG.md`.
