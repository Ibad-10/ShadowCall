# PRODUCT.md: ShadowCall

> Written from the owner's brief, without a live interview (the owner was asleep or busy during the build). Assumptions are marked *(assumed)*.

## What it is
ShadowCall runs a cheap open model **in the shadow** of a business's frontier model, on the same live calls, and switches each sub-task over only when a verifier shows the small model is at least as accurate on held-out calls. It's built for a UK dental practice's AI phone line, but the pattern is any voice or chat agent with checkable rules.

## Who uses it
- **Operators / practice managers** check that it's safe: what got switched, what it saves, and what went wrong. They use it on a laptop at work.
- **Engineers** look at calls, disagreements and corrections, and approve fixes.
- **Judges and visitors at an expo** see the landing page and the overview on a projector or a laptop, in a dark hall, at night *(assumed from the hackathon setting)*.

## Jobs
1. "Is it safe to let the small model answer this?" The promotion gate shows its evidence.
2. "What is it saving me?" Pence per call, frontier versus as served.
3. "Where is the frontier wrong, and did we fix it?" Disagreements, corrections and the Fix queue.
4. "The rules changed. Does it re-qualify?" A policy diff and fast refresh.

## Voice
Plain British English. Confident, precise and unhyped. Numbers come before adjectives. Never claim a mock number is a result; label mock mode everywhere.

## Constraints
- FastAPI backend. It must run on Windows and Linux, offline in mock mode, with no CDN at runtime.
- Keys are never shown, only present or absent.
- Mubit's limits: training starts by itself at 25 kept examples; there's no adapter model ID.
