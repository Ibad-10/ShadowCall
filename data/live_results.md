# Live — real Mubit calls

Generated 2026-10-24T05:04:58+00:00 (UTC). Frontier `gpt-6-sol` vs small `openai/gpt-oss-20b`, both through Mubit. Scored by our own checker.

## eval_base (2026-10-24T04:25:52+00:00 to 2026-10-24T04:45:45+00:00 UTC, cards `cards_v1_s7.jsonl`)

Note: 18 of 172 small-model calls took over 10 s while waiting on Groq's 8,000 tokens-a-minute limit; medians are shown so these waits barely move them, but the summed per-call time includes them.

| Sub-task | Lane | n | Correct | Accuracy | Median latency ms | Median pence | Red-flag misses / red-flag calls | Failed on red-flag calls |
|---|---|---|---|---|---|---|---|---|
| extract | teacher | 43 | 41 | 95.3% | 2016 | 0.1118 | 0 / 0 | 0 |
| extract | shadow | 43 | 28 | 65.1% | 623 | 0.0057 | 0 / 0 | 0 |
| policy_check | teacher | 43 | 33 | 76.7% | 2052 | 0.1845 | 0 / 0 | 0 |
| policy_check | shadow | 43 | 21 | 48.8% | 737 | 0.0101 | 0 / 0 | 0 |
| form_fill | teacher | 43 | 35 | 81.4% | 1740 | 0.1683 | 0 / 0 | 0 |
| form_fill | shadow | 43 | 11 | 25.6% | 1323 | 0.0080 | 0 / 0 | 0 |
| summary | teacher | 43 | 43 | 100.0% | 1689 | 0.0933 | 0 / 0 | 0 |
| summary | shadow | 43 | 43 | 100.0% | 633 | 0.0048 | 0 / 0 | 0 |

Per call (teacher, all 4 sub-tasks, n=43): median 0.5682p, median 7612.368 ms summed.

Per call (shadow, all 4 sub-tasks, n=43): median 0.029p, median 7707.6859 ms summed.

## eval_redflag (2026-10-24T04:49:22+00:00 to 2026-10-24T05:02:24+00:00 UTC, cards `cards_v1_s31_heldout_redflag.jsonl`)

Note: 5 of 54 small-model calls took over 10 s while waiting on Groq's 8,000 tokens-a-minute limit; medians are shown so these waits barely move them, but the summed per-call time includes them.

| Sub-task | Lane | n | Correct | Accuracy | Median latency ms | Median pence | Red-flag misses / red-flag calls | Failed on red-flag calls |
|---|---|---|---|---|---|---|---|---|
| extract | teacher | 15 | 0 | 0.0% | 2492 | 0.1316 | 0 / 15 | 15 |
| extract | shadow | 15 | 0 | 0.0% | 505 | 0.0058 | 2 / 15 | 15 |
| policy_check | teacher | 15 | 15 | 100.0% | 1683 | 0.1473 | 0 / 15 | 0 |
| policy_check | shadow | 13 | 12 | 92.3% | 472 | 0.0069 | 1 / 13 | 1 |
| form_fill | teacher | 15 | 15 | 100.0% | 1374 | 0.1411 | 0 / 15 | 0 |
| form_fill | shadow | 14 | 4 | 28.6% | 464 | 0.0070 | 10 / 14 | 10 |
| summary | teacher | 15 | 15 | 100.0% | 1806 | 0.0987 | 0 / 15 | 0 |
| summary | shadow | 12 | 12 | 100.0% | 562 | 0.0048 | 0 / 12 | 0 |

Per call (teacher, all 4 sub-tasks, n=15): median 0.5211p, median 7457.7285 ms summed.

Per call (shadow, all 4 sub-tasks, n=12): median 0.0246p, median 3823.1144 ms summed.

## Training sends

| Sub-task | Probes | Probe passed | Correction turns | Fixed | record=full sent | Re-verified |
|---|---|---|---|---|---|---|
| extract | 30 | 27 | 3 | 3 | 30 | 30 |
| policy_check | 32 | 24 | 8 | 7 | 31 | 30 |
| form_fill | 30 | 23 | 7 | 7 | 30 | 30 |
| summary | 30 | 30 | 0 | 0 | 30 | 30 |

## Findings

- Red-flag set, extract: every reply (both models) fails on preferred_date. The card truth sets it to null for a red-flag emergency, but the extract prompt only says 'emergency without red flags -> today'. That is a gap in our spec, not a model error; the red_flags field itself is scored separately as red-flag misses.
- Held-out set cards_v1_s7 has no red-flag calls, so red-flag numbers come only from the 15-card supplementary set (small n).
- Some red-flag small-model calls are missing (n < 15): Groq's 200,000 tokens-a-day limit was reached; not retried.
- Arms C/D (adapter) not run: Mubit gives the inference key no adapter endpoint, kept count or training status.

Estimated spend for this run: $4.57 (provider list prices + $0.005 per Mubit request; an estimate, not a bill).
Pence: provider tokens only, at 75p per US$; Mubit's per-request fee is not included.
