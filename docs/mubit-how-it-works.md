# How Mubit works, and what it means for ShadowCall

24 Oct 2026, about 04:00 BST. Sources:

- **[D]** the public docs at docs.mubit.ai. Local copy: `docs2/llms-full.txt` and `docs2/pages/*.md`.
- **[SDK]** PyPI `mubit-sdk` 0.13.2 and npm `@mubit-ai/ai-sdk` 0.8.0, both read from source.
- **[GH]** the github.com/MubitLabs repos.
- **[C]** the public console JavaScript bundle at `app.mubit.ai/console/assets/index-CRzmPwXR.js`, saved as `docs2/console/index.js`. This is **not documented** and may change. I only read it. I did not drive a signed-in session.
- **[P]** our own live probes with the inference key. No key appears anywhere in this file.

## 1. The short version

Mubit is a recording proxy in front of your provider. It passes each call through and records it. It also groups calls into **tasks** and works out which recorded replies are good enough to keep. Once a task has enough **kept examples**, it trains a small model for that task (an **adapter**). It then tests each adapter version against the provider model's own answers. [D index, concepts]

You never call an adapter by name. Your app keeps sending its usual model ID, and the **Served by** column in Requests shows who actually answered. [D model-ids, requests]

## 2. How a task is formed

- **What makes a task:** the instructions, tools, tool choice, output format and model. The model is read without a date suffix or `-latest`. [D tasks-and-sessions; model-ids]
- **What doesn't count:** "the messages after the instructions", `temperature` and `max_tokens`. [D tasks-and-sessions L19] A multi-turn correction conversation therefore stays in the **same task**.
- **Small changes don't split a task:** changes in spaces, numbers, dates, times and IDs inside the instructions are ignored. Other changed words create a new task. That is why ShadowCall keeps per-call facts out of the system prompt.
- **Sessions** come from `metadata.thread_id`, `session_id` or `conversation_id`. Otherwise Mubit uses the instructions plus the first user message. "Mubit sets a task's test cases aside by session." [D tasks-and-sessions]
  - [P] `metadata.session_id` is rejected on both of our lanes, so we rely on the fallback.
  - A correction turn has the same instructions and the same first user message, so it falls in the **same session** as the original call. It can't leak into the test split under a different session.
- **The console names:** tasks are "lanes" or "workloads" inside the console. [C]

## 3. Kept and not kept

- **Definition:** a kept example is "a call Mubit accepts for training or testing. Not every recorded call becomes a kept example." A call recorded without its request and reply is never kept. [D concepts; first-adapter L15]
- **Recording headers:**
  - `x-middleware-record: metadata` or `off`, or `x-middleware-store: false`, means the call does not appear in Requests and can't be kept.
  - `off` also drops the task fingerprint.
  - A header can lower what is recorded but never raise it. [D requests "Why a call isn't listed"; troubleshooting]
- **Who decides what is kept** [C]: a built-in **reviewer** (an LLM rater) reads new calls. Console strings include:
  - "Reviewer: {n} new calls, {a} kept, {s} rejected"
  - "rated N up and M down"
  - "Over today's review limit" (setting `adapters.rate.max_per_day`)
  - The console's kept count is `counts.rated_up`.
  - A rating's source is shown as "by a person", "from the app", "by the reviewer" or import.

## 4. Ratings, feedback and corrections

- **In the docs:** the only rating control is the Requests panel's **Rate this reply: Good / Bad**. It is in the UI only. [D requests L48]
- **Undocumented engine route** [C]: `POST /v2/traces/{id}/feedback {rating:"up"|"down", comment≤500}`.
  - [P] With our inference key, every `api.mubit.ai/v2/*` path we tried returned **404 `unknown_route`**: health, status, lanes, traces, adapters and adapters/config.
  - So our app **can't** rate calls itself.
- **Read-only keys:** keys come with "Inference" or "Read only: reads its records" permissions. [D mubit-keys] A read-only key gets `403 key_permission` on model calls. That implies a records API exists, but it isn't documented.
- **No corrected-output API:** there is no documented way to hand Mubit a corrected reply. Kept examples can only come from replies that went through the gateway.
- **Import past calls** (Langfuse, Braintrust or Logfire) covers only calls made before the project's first live call, and is for admins only. [D import-past-calls] We can't use it now.

## 5. The old SDK: `record_outcome`, `feedback`, `learn`

- **What it is:** `mubit-sdk` 0.13.2 is the earlier **memory engine** (remember, recall, reflect, lessons).
  - `record_outcome` posts to `/v2/control/outcome`.
  - `feedback(handoff_id, verdict)` posts to `/v2/control/feedback`.
  - `learn` wraps OpenAI, Anthropic and Gemini clients to add memory context.
  - It never mentions adapters, the gateway or kept examples. [SDK `mubit/client.py`, `mubit/learn/*`]
- **The npm package:** `@mubit-ai/ai-sdk` 0.8.0 is "Vercel AI SDK middleware backed by MuBit memory engine" (`recordOutcome`, `getLastReferenceIds`). [SDK npm]
- **Live result** [P]: these `/v2/control/*` paths return **404 `unknown_route`** with our key. **They do nothing to tasks, kept examples or adapters.** We don't use them.
- **The MubitLabs repos** are memory-engine demos (demo, minima, mubit-loop-demo, Mubit-x-Voice-Agents-Demo, latte-bench and others), plus mubit-cli, which ships binaries only. latte-bench uses the base URL `https://api.mubit.ai/openai/v1/`, the same one we use. [GH]

## 6. The training trigger and its limits

- **When a task trains:** by default at **25 kept examples**, and "the count your console shows is the source of truth". [D first-adapter L15]
- **Statuses:** Collecting examples → Reviewing examples → Training → Testing. [D first-adapter]
- **What can make it wait:**
  - "today's training limit", which resets at 00:00 UTC; the number isn't stated [D L519];
  - a pause between trainings;
  - "Waiting for more examples: k of need";
  - "Waiting for new examples".
- **No manual control:** there's no retry button. Training has to be switched on per workspace, and there's no Adapters page until it is. [D first-adapter]
- **Correcting my earlier note:** "3 a day" is the **Try models adapter starts** limit, not the training limit. [D first-adapter L560]
- **Settings in the console** [C]:
  - `adapters.min_rows` / `max_rows`, `replay_fraction`, `warm_start`
  - `adapters.refresh.min_new_rows` / `min_new_fraction`
  - `adapters.gate.parity_points` / `min_judged_rows`
  - `data.train_opt_out` and `data.retention_days`

## 7. The adapter base model

**Not named anywhere public.** The console shows that adapters are served on vLLM [C]. Ask the Mubit team.

## 8. How versions are evaluated

- **The test:** each version is tested on the task's held-out test cases (split by session) against **the provider model's answers**. [D index, concepts]
- **Results:**
  - `Passed`
  - `Below target`: "Matched a% of your provider model's answers on n test cases · needs need%", or "Passed a% of n required test cases · needs 100%"
  - `Malformed tool calls`
  - `Prompt only`: the base model with the prompt alone did as well, so no adapter is needed
  - `Not tested` [D first-adapter L504]
- **What this means for us:** Mubit measures *agreement with the frontier*, not correctness. ShadowCall's own gate checks correctness against the policy engine. We need both.

## 9. Calling and serving an adapter

- **No adapter model ID:** your app keeps its model IDs. [D model-ids]
- **Try models:** compares the provider model with an adapter side by side. Those calls are "not stored · trains nothing", and there's a daily quota of 3 adapter starts. [D first-adapter L489, L560]
- **Routing in the console** [C]:
  - Rule: "match ≥ X% → adapter · below → fallback/refused".
  - Engine actions: `auto_promote`, `auto_demote`, `auto_rollback`, `auto_retire`.
  - Settings: `promotion.bar`, `floor`, `min_pairs`, `min_sessions`, `shadow_rate`, `canary_percent`, `min_canary_calls`, `audit_rate`.
  - Call copies: "silent-test" (shadow) and "spot-check" (audit).
- **Served by** values: Your provider / Your adapter / Prompt only / A person / No model. [C; D requests]
- **Response headers** [C]: the console's own chat route reads `x-middleware-served-by`, `x-middleware-pathway` and `x-middleware-trace`. [P] Our `api.mubit.ai` replies **don't carry them**.
- **What we can see:** only `x-middleware-request-id` (`mreq_` + 32 hex characters). The only way we can tell whether an adapter served a call is the console's Served by column.

## 10. Console APIs (undocumented, [C])

These are reached through `/mapi/engine/...` with a Clerk session:

- `/v2/lanes` and `/v2/lanes/{id}/log`
- `/v2/traces/{id}/feedback` and `DELETE /v2/traces/session/{id}`
- `/v2/adapters`, `/config` and `/jobs`
- `/v2/adapters/{id}/serving|rollback|kill|promotion_history`
- `/v2/adapters/{id}/versions/{v}/promotion|demote`
- `/v2/evals` and `/v2/evals/live`
- `/v2/pathways` (with resolve and calibrate), `/v2/deployments` and `/v2/loop/policy`

None of these can be reached with an inference key. [P]

## 11. Other limits we measured [P]

- **Groq lane:** 1,000 requests a day and 8,000 tokens a minute (`x-ratelimit-*` headers).
- **API limits** [D api]:
  - Timeouts: 10 s to connect, 610 s to first byte, 15 min of silence, 60 min in total.
  - Starter-credit request bodies: 8 MiB.
  - Mubit records up to 32 MiB of each request, and the first 4 MiB plus the last 256 KiB of each reply.

## 12. What this changed in ShadowCall: the correction turn

- **The problem:** plain resamples fixed **0 of 27** live mistakes, because the frontier just repeated itself.
- **The new flow:**
  1. The probe call (`record=metadata`) goes through the checker.
  2. If it's wrong, a **correction turn** follows on the same task: [original request, the frontier's wrong reply, "Correction from the practice's checker (policy engine v1 / call card): field: you gave X; the engine gives Y…"].
  3. If the corrected reply passes, that whole conversation is replayed with `record=full`. Mubit records it, and the reviewer can keep it.
  4. If it still fails, the checker's own repair goes to a **Fix queue** for a person. It is never sent to Mubit, because there's no API to send it. Approved fixes are exported (`/api/corrections/export`) for later training elsewhere.
- **Live result** (`data/correct_live.db`, `data/correct_live.log`): **5 of 5** frontier mistakes were fixed by a single correction turn.
  - The training card (0002 form_fill, `treatment`) was fixed twice.
  - The held-out cards were 0010 policy_check (`rule_ids`), 0006 form_fill (`fee_gbp`) and 0010 form_fill (`treatment`). These stay `metadata`, so they're never kept.
  - Only **one** `record=full` keep was sent: `mreq_01a16bd7bec9746195ac38751124c852` (form_fill).
- **Open questions:**
  - Does the reviewer keep multi-turn rows?
  - Does training learn the *last* assistant turn? Production calls are single-turn.
