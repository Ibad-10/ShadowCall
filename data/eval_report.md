# Held-out eval (mock mode, 42 held-out calls)

> MOCK MODE: simulated models. These numbers test the harness; they are not results.

| Sub-task | Arm | Accuracy | Red-flag acc | Pence/call | Latency ms |
|---|---|---|---|---|---|
| extract | teacher | 85.7% |  | 0.050 | 685 |
| extract | shadow | 66.7% |  | 0.008 | 221 |
| extract | adapter_raw | 90.5% |  | 0.008 | 185 |
| extract | adapter_verified | 100.0% |  | 0.008 | 185 |
| policy_check | teacher | 88.1% |  | 0.059 | 689 |
| policy_check | shadow | 71.4% |  | 0.011 | 223 |
| policy_check | adapter_raw | 85.7% |  | 0.011 | 193 |
| policy_check | adapter_verified | 97.6% |  | 0.011 | 193 |
| form_fill | teacher | 90.5% |  | 0.065 | 696 |
| form_fill | shadow | 71.4% |  | 0.011 | 224 |
| form_fill | adapter_raw | 95.2% |  | 0.011 | 193 |
| form_fill | adapter_verified | 100.0% |  | 0.011 | 192 |
| summary | teacher | 81.0% |  | 0.033 | 684 |
| summary | shadow | 64.3% |  | 0.005 | 220 |
| summary | adapter_raw | 83.3% |  | 0.005 | 188 |
| summary | adapter_verified | 97.6% |  | 0.005 | 188 |
