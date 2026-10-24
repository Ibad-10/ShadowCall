# Pre-registration (write the date/time and commit hash BEFORE the first training call)

- **Committed at:** ____ (BST)  **Commit:** ____
- **Niche:** inbound calls to one (fictional) UK dental practice, Riverside Dental. Policy fixtures: `shadowcall/policy/policy_v1.md`, `policy_v2.md`.
- **Sub-tasks (one Mubit task each, fixed instructions):** extract, policy_check, form_fill, summary.
- **Verifier (ground truth):** call-card truth for extract; deterministic policy engine for policy_check, form_fill and summary disposition; rule-based claim check (+ Banyan Sapling `supported` if available) for summary text. The frontier is never the judge.
- **Data:** synthetic call cards, `shadowcall gen --n 160 --seed 7 --policy v1` and `--seed 21 --policy v2`. Split by session hash: ~30% held-out. Held-out calls go through Mubit with `x-middleware-record: metadata`, so they are never kept examples.
- **Arms:** A frontier single-shot · B open base model prompt-only (Mubit compat route) · C adapter trained on raw frontier replies (learning off, separate Mubit project) · D adapter trained on verified replies + resampled corrections (learning on).
- **Primary metric:** held-out exact-field accuracy per sub-task. **Secondary:** red-flag (R5) accuracy, pence per call, median latency.
- **Decision rule (gate):** switch a sub-task only if D ≥ A + 0 pp on ≥ 20 held-out calls AND zero red-flag misses. Roll back on a policy change or if live verified accuracy over the last 10 served calls < 80%.
- **Never-claim list:** mock-mode numbers; "beats GPT" in general; latency we did not measure end to end; any adapter number we did not see in Mubit (Try models or a callable adapter).
- **Honest negatives we will report:** sub-tasks that stay in shadow; arms we could not run (e.g. C if no second project).

## Live run log, Sat 24 Oct 2026 (added after the fact; the header above was never filled in before training)
- **Training sends (05:16–05:24 BST):** 32 fresh training-split cards from `cards_v1_s7.jsonl` (cards 11–52; cards 1–10 were used in the earlier smoke runs). 30 re-verified `record=full` sends per sub-task, plus 1 policy_check replay that failed re-verification (rate it Bad in the console). No held-out card was ever sent with `record=full` (checked in `data/live_run.db`).
- **Held-out eval (05:25–05:45 BST):** the 43 held-out cards in `cards_v1_s7.jsonl`, arms A and B only. Seed 21 / policy v2 cards were not run.
- **Deviation:** that held-out set contains no red-flag calls, so the red-flag check had n = 0. A supplementary held-out set of 15 red-flag calls (`gen` seed 31, held-out split, filtered to `red_flag`, saved as `data/cards_v1_s31_heldout_redflag.jsonl`) was added after the base eval and run as `eval_redflag`.
- **Arms C and D:** not run. Mubit exposes no adapter endpoint or status to the inference key.
