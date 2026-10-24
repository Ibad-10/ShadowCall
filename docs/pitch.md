# ShadowCall: pitch materials

Put the real numbers in where you see `[X]`. Never use mock numbers.

## 1. Three-minute demo video script (aim for 2:50)

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:15 | Phone ringing; the dashboard | "Every call to a dental practice's AI receptionist makes four frontier-model calls. Nobody checks them against the practice's own rules. ShadowCall does, and then it replaces them, one at a time, with small models Mubit trains." |
| 0:15–0:40 | A live ElevenLabs call: "Thursday week at half two, no sorry, Wednesday" | "The live agent stays on the frontier model, routed through Mubit. That's shadow mode, so nothing changes for the caller. After the call, four sub-tasks run: understand, policy check, booking form, wrap-up." |
| 0:40–1:05 | Disagreement log; a red frontier cell with R4 | "Here the frontier forgot the £30 late-change fee. Our verifier is the practice's policy rules, not the model, and it catches the mistake. Across [N] calls, the frontier got [X]% of late changes wrong." |
| 1:05–1:35 | Corrections count rising; Mubit Tasks `25 of 25`, then `Training`, then Adapters `Passed` | "That mistake becomes a correction. We never let Mubit keep a wrong answer. We probe, verify, then keep only the verified reply, or a corrected resample. So Mubit's adapter learns the practice's rules, not the frontier's blind spots. Here's the model update." |
| 1:35–2:00 | Results table A/B/C/D; the gate flips to `switched` | "On [n] held-out calls, the adapter trained on raw frontier answers scored [C]%. With our verifier and corrections it scored [D]%, against the frontier's [A]%. Only then does the gate switch extraction over. One missed 999 case and it would never switch." |
| 2:00–2:15 | Pence per call | "Cost per call goes from [Y]p to [Z]p, and 20% of calls are still audited by the frontier." |
| 2:15–2:45 | Press Policy v2: rollback, disagreements, re-promotion | "Monday's policy change: hygiene is now 45 minutes, and new patients pay a deposit. The gate rolls back instantly. The old adapter is stale, and we can see it. Fresh corrections retrain it, and [T] later it re-qualifies. That's fast refresh." |
| 2:45–2:55 | Logo; repo | "ShadowCall. Shadow first, verify always, switch only when it's earned. Every call goes through Mubit." |

## 2. Deck outline (8 slides, export as PDF)

1. **Title.** ShadowCall: verifier-gated shadow distillation for voice agents. Team, track (Recurring tasks + Fast refresh).
2. **Problem.** Four frontier calls per phone call, unverified. Pence per call times volume. Examples of policy mistakes: the fee, the guardian, a red flag.
3. **How it works.** The architecture diagram (spec §6). Shadow, then verify, then keep only verified, then train, then gate, then switch, then audit.
4. **Using Mubit properly.**
   - the gateway on three routes;
   - sessions;
   - `x-middleware-record` as data control;
   - tasks, kept examples, adapters;
   - Try models;
   - request IDs in the log;
   - why scoring against the teacher is safe once the kept set is verified.
5. **Results** (live, n stated). Accuracy per sub-task for A/B/C/D, red-flag accuracy, pence per call, latency.
6. **The correction becomes a model update.** Before and after a correction, with version history screenshots.
7. **Fast refresh.** The v1 → v2 timeline: rollback, stale disagreements, retrain, re-promote, and the time taken.
8. **Honesty and what's next.** The PREREG link, the never-claim list, what didn't work (e.g. sub-tasks still in shadow, arms we couldn't run), and next steps (per-turn extraction, more practices).

## 3. Expo pitch (1–2 minutes, at the table)

"Hi, I'm Ibad. This is ShadowCall.

AI phone receptionists make four frontier-model calls on every call. Nobody checks those calls against the business's own rules, and they cost real money.

We put the practice's agent in shadow mode through Mubit. It keeps answering on the frontier. Behind it, every sub-task (understanding the caller, the policy check, the booking form, the wrap-up) is checked by the practice's policy rules.

When the frontier gets it wrong, say it forgets the late-change fee, that becomes a correction. Mubit only ever keeps verified answers, so the small adapter it trains learns the rules, not the frontier's mistakes.

Each sub-task switches to its small model only after it beats the frontier on held-out calls, and never if it misses a single 999 case. Here it is: [point to the gate flip]. Here's the cost per call: [Y]p down to [Z]p.

And when the policy changes, watch [press v2]: it rolls back by itself and re-learns.

Want to call it? Pick a card and read it out."

**Have ready:** a phone with the agent's number, printed call cards, and the dashboard on a big screen.

## 4. Five-minute stage script (finalists, 12:30 GMT)

| Time | Beat |
|---|---|
| 0:00–0:30 | **Hook.** Read a card into the phone live: "My son's 9, can we do Saturday at half eleven?" "That call just triggered four model calls. Let's see what they got right." |
| 0:30–1:15 | **Problem and insight.** Mubit learns by copying the frontier. If the frontier is wrong, you copy the mistake. Our fix: the business's rules decide what Mubit keeps. |
| 1:15–2:15 | **Live dashboard.** The call's sub-tasks, then a disagreement (the frontier missed the guardian rule, R6), then the correction, then the Mubit console: Tasks, Adapters → History (`Passed`), Try models side by side. |
| 2:15–3:00 | **Results.** The A/B/C/D table. C versus D is our ablation and proves the corrections matter. The red-flag block. Pence per call. |
| 3:00–4:00 | **Fast refresh live.** Press Policy v2: rollback, stale disagreements, then the v2 adapter re-promoted (show the timestamps). |
| 4:00–4:40 | **Honesty.** The pre-registration, what we didn't prove, and what Mubit could add (a callable adapter would make shadow serving fully native). |
| 4:40–5:00 | **Close.** "Shadow first. Verify always. Switch only when it's earned." Invite applause. |

**Backup:** if the phone fails, use the text simulator. If the gateway fails, play the video, then switch to mock mode with "SIMULATED" shown.
