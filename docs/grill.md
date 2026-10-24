# ShadowCall: the grilling

British English. I asked the questions in two voices:
- **J**: a hard Mubit judge.
- **E**: a sceptical engineer.

I answered every question from the evidence and cite it. The sources are:
- the research pack, `mubit-nightshift-research.md` (cited as RP);
- the Mubit docs dump, `llms-full.txt` (cited as DOCS, by line);
- the Grok passes `A.md`, `B.md`, `C.md` and the new fact-check pass `D.md`, which used grok-4.6 at xhigh with live search on 24 Oct.

Anything I inferred is marked **[guess]**. For each branch I give the decision, then the fix that is now in the code at `shadowcall/`.

I used Matt Pocock's grill-me / grilling skill (design tree, one branch at a time, each question answered with a recommendation) and Superpowers' brainstorming skill (approaches, then trade-offs, then design). The user-approval gates were replaced by Ibad's "crack on". He reviews later.

---

## Round 0. The premise

**J: Say it in one sentence.**
A company's phone agent keeps answering live calls on its frontier model. Behind it, Mubit learns a small adapter for each sub-task of the call. Each sub-task switches over only when it beats the frontier on held-out calls, judged by the company's own policy rules.

**J: Who pays for this?**
A practice or contact centre whose voice agent makes four or more frontier calls per call. Two things matter to them:
- **Cost.** The Mubit pitch is "Make your frontier spend smaller" (RP §1).
- **Fewer policy mistakes.** Today nobody checks the frontier's mistakes, such as missing the 24-hour fee or the guardian rule.

**E: Isn't "shadow mode, then promote" just a normal ML rollout?**
Yes, and that's the point. It's how cautious teams actually adopt a cheaper model. What's new is doing it per sub-task inside one voice call, with a policy verifier as the referee, so it's automatic and auditable. Mubit's own docs say "Passing a test does not guarantee suitability for every input; review representative examples" (DOCS 466). Our gate is that review, automated.

---

## Round 1. Mubit mechanics (the weakest branch)

### 1.1 Mubit scores adapters against the frontier's answers. Doesn't that contradict "beat the frontier via a policy verifier"?

**J:** "Each adapter version is tested against your provider model's answers" (DOCS 13, 463). "Below target" means "answers less like your provider model" (DOCS 986). If the adapter's goal is to copy the frontier, how can it beat it?

**Answer: it does conflict if you send raw traffic. We remove the conflict by controlling what Mubit keeps.**
- Mubit trains only on kept examples, and "a call recorded without its request and reply is never a kept example" (DOCS 1232).
- `x-middleware-record: metadata` keeps the call's record but not its request and reply (DOCS 3058).

So for every training call we do this:
1. **Probe.** Send it with `record=metadata`, so nothing is kept.
2. **Verify** the reply with the engine and the call-card truth.
3. **If it passes,** replay the identical request with the same `seed` and `record=full`. That reply is kept.
4. **If it fails,** that is a frontier error, and it becomes a correction. We resample at T=0.7, still with `record=metadata`, until a reply passes. Then we replay that one with `record=full`.

Temperature doesn't change the task; only instructions, tools, tool choice, output format and model do (DOCS 2519–2529). So the corrected reply lands in the same task.

**Result:** every kept example is verified correct. "Match the teacher" now means "match verified behaviour". The adapter can then score higher than the single-shot frontier on held-out, because the frontier's blind-spot errors never entered training. This is rejection-sampling distillation.

**Weakness that remains:**
- `seed` replay isn't guaranteed to reproduce the reply exactly. We verify the replay, and log any mismatch as `kept_unverified`, to be rated Bad in the console.
- Mubit's own "Passed" still means "matches the teacher's kept answers". We never quote it as accuracy. We quote **our** verifier on **our** held-out set.

**Fix in code:** `pipeline.Pipeline.teacher()`, the corrections table, and the test `test_only_verified_teacher_replies_are_kept`.

### 1.2 How do corrections actually reach Mubit training?

**J:** "There is no public API to submit feedback, a rating, or a corrected reference output" (D §1). The console's Good/Bad rating has "no training link published" (D §1). So where is your "correction becomes a model update"?

**Answer: through the only documented channel, which is what gets kept** (see 1.1). A correction is a verified frontier reply that replaces a wrong one in the training set. On the demo screen:
1. The frontier makes an error (red in the disagreement log).
2. The verifier says why, e.g. `R4 fee missing`.
3. The resample is kept.
4. The task's count ticks up (`24 of 25 examples`, DOCS 955).
5. Mubit trains a new version.
6. The adapter's held-out score on that rule goes up.

We also rate the bad live reply **Bad** in the console. That's cheap and visible, but we don't claim it trains anything.

**Backup channel:** the "Import past calls" feature takes Langfuse, Braintrust or Logfire traces "before your project's first call through Mubit" (DOCS 2688–2745). [guess] We could write corrected traces to Langfuse and import them into a fresh project. That's slow and awkward, so it's a Won't unless staff recommend it.

**Ask staff (needs.md Q1):** does Bad exclude a call from kept examples? Is there a hidden correction API?

### 1.3 Can the adapter even be called for a real shadow run?

**J:** "There is no Mubit model ID: you can't send a call to an adapter by naming it as the model" (DOCS 3085, 2685). "Try models marks its calls `not stored · trains nothing`" (D §2).

**Answer: not through any documented API.** So the code has three lanes for the small model, chosen automatically (`evalh.serving_lane`):
1. **`MUBIT_ADAPTER_*` set.** Used if staff give us a callable adapter. The console's "Served by" column hints the gateway can serve something other than the provider (DOCS 2422). [guess]
2. **Open base model, prompt only, through Mubit's compat route**, e.g. `https://api.mubit.ai/compat/groq/v1` (DOCS 1679, 1803). This is real, live, and every call still goes through Mubit. This lane is arm B, and the gate can promote it too. Mubit's own `Prompt only` result exists because "the base model … did as well as the adapter" (DOCS 988), so promoting the base model is a legitimate outcome.
3. **Try models replies pasted into a JSONL** and scored with `cli import-tryouts`. This is manual, and capped by the daily Try models quota (D §4). Use it for one or two sub-tasks on about 20 held-out calls.

**Fix in code:** `MUBIT_ADAPTER_BASE_URL/MODEL`, `evalh.import_tryouts`, and the arm table in `PREREG.md`.

**Honest claim on stage:** "Live shadow serving runs on the open model through Mubit. Adapter numbers come from Try models on held-out calls." If staff expose a callable adapter, that sentence gets better.

### 1.4 The 25-example threshold and the training limits

**E:** Here are the limits:
- 25 kept examples by default (DOCS 497).
- A daily training limit and a pause between trainings, with no number published (D §4).
- "3 adapter starts for this UTC day" (D §4).
- Resets at 00:00 UTC, which is **01:00 BST on Sunday**, an hour before the clocks go back.
- Code freeze is **Sun 05:00 GMT**.

Four sub-tasks times two policy versions is eight trainings. Does that fit?

**Answer: no, so we cut.**
- **Sat (UTC day 1):** train **extract** and **form_fill** on v1. That uses 2 of the 3 adapter starts. The spare covers a retry.
- **Sun after 01:00 BST:** train **form_fill on v2**, the fast-refresh moment.
- policy_check and summary stay "base model in shadow" unless the limits allow more.

**Data needed per training:** about 30 to 40 training calls per sub-task. Not every call becomes a kept example (DOCS 497), so plan on roughly 40.

**Data plan:**
- `cli gen --n 160` gives about 118 training and about 42 held-out cards.
- Each card makes 4 sub-task calls. Verified keeping costs about 2 calls per kept example, plus resamples on the roughly 10–15% of calls the frontier gets wrong.
- So about 118 × 4 × 2.2 ≈ 1,040 gateway calls. At $5 per 1,000 runs (RP §1) that's about $5, plus the frontier on the starter credit (`gpt-6-luna`, DOCS 119).
- v2 needs another 40 or so cards.

**Fix in code:** `synth.generate`, the session split, and `cli train --limit`.

### 1.5 "Prompt only" and "Below target" risks

**E:** On templated transcripts the base model might already match the frontier. Mubit then returns `Prompt only` and you have no adapter to show.

**Answer:** that's a real risk. Three mitigations:
- Make the task hard enough with hard-case tags: self-corrections, "Thursday week", "half two", children, late changes, Saturday hours, new-patient hygiene, plus ASR noise (Should).
- If the result is `Prompt only`, report it as a finding: "the cheapest lane wins; the gate switches to the base model".
- Pre-register both outcomes.

---

## Round 2. Voice

### 2.1 Latency

**E:** The ElevenLabs Mubit demo's budget is about 800 ms (RP §4). Mubit adds a hop, and its overhead is not published; the console shows "Where the time went" (D §8).

**Answer:** the sub-tasks are **off the voice path**. They run after the call, or asynchronously per turn (Should). Only the live conversational reply is on the path, and that's the company's frontier through Mubit, which is shadow mode and unchanged. We use ElevenLabs' buffer-words trick, `SHADOWCALL_BUFFER_WORDS="One moment... "` (D §5). We measure the hop from "Where the time went" and quote that number only.

**Fix in code:** `voice.py`.

### 2.2 Can ElevenLabs' custom LLM point straight at the Mubit gateway?

**Answer: don't.** ElevenLabs sends `user_id` and `elevenlabs_extra_body`, and its own sample strips them (D §5). [guess] Passing them on could 400 at the provider. Mubit's own voice demo used a proxy (D §5).

So we run a thin relay at `POST /v1/chat/completions`. It strips those two fields, sets `metadata.session_id` from the conversation ID, forwards as SSE to Mubit, and checks the secret. The custom LLM can't be used with Realtime models (D §5), which is fine.

**Fix in code:** `voice.clean_body`, the relay, and the post-call webhook parser. Tested.

### 2.3 Real calls have no ground truth

**J:** Then how do you verify a live call?

**Answer: call cards.** The demo caller (Ibad, or a judge) reads the script on card #k aloud. The real ASR transcript replaces the card's text, and the card's truth stays as the reference. So a real voice call is scored exactly. That's novel, and it fixes Mubit's own admission: "Nothing ran end to end through a real ElevenLabs call" (RP §3, D §7).

**Fix in code:** `POST /api/demo-card/{id}` and `/webhook/elevenlabs/post-call`.

---

## Round 3. Verification and the rules

### 3.1 Sapling hosting

**Facts (D §6):**
- "This model isn't deployed by any Inference Provider."
- 46 GB BF16 on an H200 reference machine.
- No quantised version.
- Labels: `supported`, `violation`, `insufficient_information`, `inconsistent_context`. The calibrated `status` can be `unsure`. It answered 45% of cases with calibration.

**Decision:**
- Sapling is a **Should**, used only on the summary's free-text claims.
- The **Must** verifier is the deterministic engine plus a strict rule-based claim checker: every time, date and £ amount in the summary must appear in the evidence.
- `unsure` counts as not verified.
- If staff host Sapling, set `BANYAN_API_URL`. Otherwise rent one 80 GB GPU only if it's ready before Saturday 18:00.

**Fix in code:** `verify.SaplingClient`, which treats only `supported` as passing and falls back to the rule check.

### 3.2 "Every LLM call through Mubit" versus Sapling

**Answer:** Sapling is a classifier with its own head, not a chat completion. Mubit can't route to a self-hosted URL anyway, because `/compat` covers only openrouter, groq, together and mistral (DOCS 1882). [guess] So it's outside the rule. **Ask staff** (needs.md Q4) and put the answer in the README.

Every **generative** call goes through Mubit:
- the teacher;
- the open model;
- any future paraphrase generator.

The relay does too.

### 3.3 Why have an LLM policy_check if you already have an engine?

**J:** Isn't that sub-task fake?

**Answer:** the company's agent already makes these four LLM calls today. We shadow their stack; we don't redesign it. The engine needs clean slots, and turning messy speech into slots is the hard part (extract). In production the engine encodes only the hard rules, and policy_check also writes the caller-facing reason. We're honest about it: policy_check and form_fill are where the engine acts as the referee, and extract and summary are where the value is.

---

## Round 4. Honest evaluation

**J: What stops you leaking held-out calls into training?**
- The split is by session hash (`synth._split`).
- Held-out calls are sent with `record=metadata`, so Mubit never keeps them.
- Every call carries `metadata.session_id`, so Mubit's own test set is also split by session (DOCS 2547).

Tested in `test_heldout_never_kept`.

**J: What's the ablation?** Four arms on the same held-out sessions:

| Arm | What it is |
|---|---|
| A | Frontier, single shot |
| B | Open base model, prompt only |
| C | Adapter trained on raw frontier replies, in a second Mubit project (`--project raw`, `MUBIT_API_KEY_RAW`). This is "learning off". |
| D | Adapter trained on verified replies plus corrections. This is "learning on". |

C versus D isolates the value of the verifier and corrections, the core claim. PREREG.md is committed before the first training call.

**E: Synthetic data is too easy.**
Agreed. Mitigations:
1. Hard-case tags.
2. A Should: an LLM paraphrase pass through Mubit, its own task.
3. Real voice calls from cards.
4. Report accuracy by tag.

If the frontier scores about 99%, the "beats the frontier" story weakens. The story then becomes: same accuracy, X pence instead of Y, plus safe switching and a fast refresh. Pre-register both.

**E: Mock mode could fake results.**
Mock mode is labelled "simulated, not results" in the UI, the report and the README, and is used only for tests and offline rehearsal.

---

## Round 5. The niche: dental booking versus retail refunds

**Decision: dental and clinic booking** (Riverside Dental, a fictional UK practice). Why:
1. **Deterministic, checkable rules:** hours, durations, new-patient, the 24-hour fee, children, red flags, the diary.
2. **A safety rule (R5, call 999 or go to A&E)** gives a hard promotion block that judges understand instantly.
3. **A real system of record**, the diary, plus the classic awkward speech: "half two", "Thursday week", "no sorry, Wednesday".
4. **Retail refunds is basically Mubit's own `mubit-loop-demo`** (an expense or support scenario with a policy change; RP §2, D §7), so judges would compare.
5. **A natural fast-refresh story:** "From Monday hygiene appointments are 45 minutes and new patients pay a £25 deposit."

**Risk:** it touches health. We never give clinical advice, and red flags always escalate.

---

## Round 6. What's new compared with Mubit's own demos

| | mubit-loop-demo | Mubit-x-Voice-Agents-Demo | **ShadowCall** |
|---|---|---|---|
| Mubit feature | memory and lessons SDK (old) | memory relay | **current adapter product** (tasks, kept examples, adapters) |
| Voice | no | harness only, "nothing ran end to end" | **real ElevenLabs calls, scored against call-card truth** |
| Unit | one task | memory block | **four sub-tasks, each with its own gate** |
| Correction | 422 rejection becomes a lesson | n/a | **verifier-filtered keeping plus resampled corrections** |
| Safety | n/a | consent gating | **red-flag miss blocks promotion; automatic rollback** |
| Ablation | cold vs warm | pre-registered EXP | **A/B/C/D with a raw-teacher project** |

Sources: D §7, RP §2.

---

## Round 7. Demo and judging

**J: Where is the correction becoming a model update?** Moment 3 in the stage script (see pitch.md):
1. A disagreement row is red for the frontier.
2. The verifier gives the reason.
3. The correction count goes up.
4. Mubit's Tasks page shows `25 of 25`, then `Training`.
5. The new version's held-out score goes up.
6. The gate flips to `switched`.

**J: How does it use Mubit beyond a proxy?** It uses:
- the gateway on three routes;
- sessions;
- record headers as the data-control mechanism;
- tasks and adapters;
- Try models;
- request IDs in the disagreement log (`mreq_…`);
- "Where the time went" for latency.

The new rules say LLM routing through Mubit feeds the "use of Mubit" score, so all generative calls go through it.

---

## Features (MoSCoW) and cut-lines

**Must** (all built in mock; live wiring is part of the plan):
1. Policy engine v1 and v2 with a fixture policy document. *built*
2. Synthetic call-card generator with truth, hard-case tags and a session split. *built*
3. Four sub-task pipeline through Mubit, with session IDs and record headers. *built*
4. Verified keeping, with frontier errors becoming corrections. *built*
5. Shadow lane (open model on the compat route) plus a disagreement log. *built*
6. Gate per sub-task: promotion on held-out evidence, red-flag block, audit sample. *built*
7. Held-out eval, arms A–D, PREREG. *built* (arm C needs a second project)
8. Dashboard with pence per call. *built*
9. Text-chat simulator fallback. *built*

**Should:**
10. ElevenLabs relay plus post-call webhook, with real calls from cards. *built, untested live*
11. Policy-change fast refresh with automatic rollback. *built*
12. Versioned rollback button. *built*
13. Try models import. *built*
14. Sapling on summary claims. *client built; needs an endpoint*
15. ASR-noise and paraphrase augmentation.

**Could:**
16. Per-turn asynchronous extraction during the call.
17. Accuracy-by-tag chart.
18. Check the ElevenLabs webhook HMAC.
19. Langfuse-import correction channel.

**Won't (this weekend):** replacing the live conversational reply with an adapter; multi-clinic support; real patient data.

**Cut-lines:**
- **Sat 14:00 BST:** if live Mubit training hasn't started, cut adapters to extract only.
- **Sat 18:00:** if voice isn't working, demo on the text simulator.
- **Sat 20:00:** if Sapling has no endpoint, drop it.
- **Sun 01:30 BST:** if v2 training isn't queued, show fast refresh as a gate rollback plus the base-model lane only.

---

## Top weaknesses and fixes

| # | Weakness | Fix |
|---|---|---|
| 1 | Mubit scores adapters against the frontier, so learning would copy the frontier's errors | Verified keeping: probe with `record=metadata`, verify, then replay with `record=full` or resample. The kept set is all-correct. The headline metric is our verifier on held-out data, not Mubit's "Passed". |
| 2 | No API takes a correction | A correction is a verified resample kept in place of the wrong reply. Also rate it Bad in the console. Staff question Q1. |
| 3 | Adapters can't be called, so a live shadow run looked impossible | Three-way lane: callable adapter if staff expose one; else the open base model through Mubit compat (live, gateable); plus a Try models import for adapter numbers. |
| 4 | Training and adapter-start limits versus 8 trainings before a 05:00 GMT freeze | Train only extract and form_fill on v1 on Saturday, and form_fill on v2 after the 01:00 BST (00:00 UTC) reset. The other two sub-tasks stay on base-model shadow. |
| 5 | Real voice calls have no ground truth, and ElevenLabs extra fields could break the gateway | Call cards read aloud, scored against card truth. A relay strips `user_id` and `elevenlabs_extra_body` and sets the session ID. The sub-tasks run off the voice path. |

Others:
- Sapling's GPU (now a Should, with a rule fallback and `unsure` counted as a fail).
- Synthetic data being too easy (hard tags, pre-registered negatives).
- Similarity to the loop demo (picked dental, not refunds).
