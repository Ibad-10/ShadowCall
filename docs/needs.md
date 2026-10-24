# ShadowCall needs, most important first

## Live status (Sat 24 Oct, 03:30–04:00 BST)

| Item | Status |
|---|---|
| `MUBIT_API_KEY` | **Have it** (box env). `/openai/v1/models` returns 200. |
| Frontier lane | **Works**: `gpt-6-sol` on the starter credit, via `https://api.mubit.ai/openai/v1`. |
| Open-model lane | **Works on the starter credit**: Groq via `https://api.mubit.ai/compat/groq/v1`. The model ID is Groq's own (e.g. `openai/gpt-oss-20b`), not `compat/groq/...` and not on `/openai/v1`. Starter Groq chat models: `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `allam-2-7b`. Starter limit seen: 8,000 tokens/min. |
| Together, OpenRouter, Mistral | `403 provider_key_missing`. Not needed. |
| `metadata.session_id` | **Rejected** by OpenAI ("only allowed when store is enabled") and by Groq ("not supported"). Both lanes now omit it, so Mubit's default session is one per card per sub-task. Ask staff (Q7). |
| ElevenLabs | **Have key**: free tier, about 6,700 of 10,000 characters left. Save it for the demo recording and expo. Collect data via the text simulator. |
| Adapter training | **Not started.** Kept examples per task are below 25 (see the smoke report). |

## Blockers (nothing live works without these). Get them by Sat 09:00 BST.

1. ~~`MUBIT_API_KEY`~~ (done). Still need confirmation that **training/adapters are on** for this workspace (the console shows an **Adapters** page).
   - Check the starter credit covers `gpt-6-luna` (or set `TEACHER_MODEL`).
   - Check the default kept-examples threshold is 25.
2. ~~Provider access for the open-model lane~~. **No provider key is needed**: the starter credit covers Groq. Optional: if 8,000 tokens/min throttles the full data run (about 1,000 calls), add a **Groq API key** under Console → Provider keys → OpenAI-compatible → Groq to get Groq's own limits.
3. **A second Mubit project key, `MUBIT_API_KEY_RAW`**, for ablation arm C (learning off). Without it, arm C is dropped and C-vs-D becomes "prompt only vs verified". That's weaker, but honest.

## Needed for the voice demo by Sat 15:30 BST

4. **ElevenLabs: tight budget.** We have the key on the free tier, with about 6,700 characters left. That's roughly 10–15 short calls in total, so: **no ElevenLabs calls during data collection.** Use 2–3 for rehearsal, 1–2 for the video take, and keep the rest for the expo. A paid Starter plan would remove the risk.
5. **A public tunnel:** `cloudflared` (free, no account needed for quick tunnels) or an ngrok auth token.
6. **Something to call from**, plus printed call cards (`GET /api/cards`).

## Nice to have

7. **A Banyan Sapling endpoint.** Either staff hosting, or one 80 GB+ GPU (H100 80 GB or H200) for about 2 h with vLLM. If it isn't ready by Sat 20:00 BST, drop it.
8. **Provider prices** (pence per million tokens) for the teacher and the open model, to make pence per call accurate. Take them from the price pages and cite the URL.
9. Screen recorder (OBS or QuickTime), a video editor that can trim to 3:00, and Google Slides or Keynote for the PDF.

## Questions for Mubit staff (ask at the first office hours)

- **Q1 Corrections.** Does rating a reply **Bad** remove it from kept examples or affect training? Is there an API to submit a corrected reference? Is our "probe with record=metadata, verify, then replay with record=full" pattern OK, and does `seed` replay count as the same task and example?
- **Q2 Serving adapters.** Can we call a trained adapter or a version, even unofficially, for shadow traffic? What values does the Requests **Served by** column take? Does a `Passed` adapter start serving automatically?
- **Q3 Limits.** What are the actual numbers for trainings per day and the pause between trainings? (The docs say the 3 starts a day are Try models adapter starts.) How many trainings a day does a workspace get? What base model or size are the adapters?
- **Q4 Every call through Mubit.** Does a verifier classifier (Sapling, which isn't a chat model) have to go through Mubit? Is the compat route OK for the open-model lane?
- **Q5 ElevenLabs.** Can ElevenLabs' custom LLM point directly at `https://api.mubit.ai/openai/v1`, or does it need our relay to strip `user_id` and `elevenlabs_extra_body`? Is there a known added latency for the gateway?
- **Q6 Judging.** Please confirm:
  - the freeze is 05:00 GMT;
  - /submit takes a repo link as well as the video and deck;
  - whether a mock-mode demo at the expo is acceptable if it's clearly labelled;
  - both tracks can be claimed.

- **Q7 Sessions.** On the starter credit, OpenAI and Groq reject `metadata.session_id`. Is there a Mubit header for the session, or should we rely on the default (instructions plus first user message)?
- **Q8 Tasks API.** Is there an API to list tasks, kept counts and version results? The docs only show the console.

## Ibad's decisions (defaults are already set; change if you like)

- The niche is the dental practice ("Riverside Dental"). Retail refunds was rejected as too close to mubit-loop-demo.
- Team name and repo visibility (public GitHub?).
- Whether the expo demo uses your real phone number on the ElevenLabs agent.

## Warning: training can start by itself

The docs say the first training starts at **25 kept examples per task**. After the two smoke runs, kept counts are:
- **extract: 14** (7 + 7);
- **summary: 14**;
- policy_check: 7;
- form_fill: 7, on the new instructions (+1 kept correction conversation, Sat 04:00);
- plus 3 each on the old policy_check and form_fill instructions, which are now orphaned tasks.

A full `cli train` run will cross 25 and **use a training slot**. Ibad decides when.
- To collect more data without training, set `SHADOWCALL_KEEP_CAP` (e.g. 23): the app stops sending `record=full` for that sub-task. Do **not** use `SHADOWCALL_VERIFIED_KEEP=false`, because that sends every training call with `record=full`. Or ask staff whether training can be paused (Q3).
- Tasks can only be confirmed in the console (**Tasks** page). There's no documented API for it (Q8).

## New questions after reading the docs and the console (Sat 04:00 BST)
- **Q9 Multi-turn kept rows.** We keep "request → wrong reply → checker's findings → fixed reply" in the same task, recorded with `record=full`. Will the reviewer keep it, and does training learn the last assistant turn? Production calls are single-turn.
- **Q10 Ratings by API.** The console uses `POST /v2/traces/{id}/feedback` (up/down) and shows rating sources ("from the app", "by a person"). With our inference key, every `/v2/*` path returns 404. Is there a supported way for the app to rate a call, or a read-only-key records API? Does a person's **Bad** rating remove a call from the kept set?
- **Q11 Serving.** The console has pathways, deployments, auto-promote and the `x-middleware-served-by` header, but our replies don't carry it. Is auto-promotion (Served by: Your adapter) on in our workspace, and which base model do adapters use?
- Note: the old `mubit-sdk` `record_outcome`, `feedback` and `learn` belong to the memory engine. They return 404 here and don't affect adapters.
- **Groq lane:** 1,000 requests a day and 8,000 tokens a minute.
- **Kept counts** (local) after the correction test: form_fill +1 (now ≤7). All tasks are well under 25.
