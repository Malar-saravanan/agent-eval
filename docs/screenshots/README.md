# Screenshots

Captured from the live UI (`http://localhost:3100/`) on the final committed
build. Use them alongside [`docs/ONE-PAGER.md`](../ONE-PAGER.md).

| # | File | What it shows |
|---|------|---------------|
| 1 | `1-experiments-list.png` | Experiments list — MAIN (300 trials, $4.36, 0 infra errors) and the nudge control. |
| 2 | `2-main-summary.png` | Main experiment summary — per-config mean score with 95% bootstrap CI, infra/timeouts/N/A, cost, latency, tokens. |
| 3 | `3-compare-noise.png` | Compare `hermes-plain` vs `hermes-full`: aggregate within-noise, per-task deltas and forest plot. Task 19 memory effect `[+0.40, +1.00]` visible. |
| 4 | `4-compare-opposing.png` | Compare `hermes-full` vs `opencode-skills`: aggregate within-noise, but per-task deltas show opposing significant effects (06, 11, 18). |
| 5 | `5-failure-analysis.png` | Failure analysis — rule-based classification per config. `capability_disabled` for hermes-plain (expected), `capability_unused` for hermes-full. |
| 6 | `6-trial-task19-memory.png` | Trial 19 (hermes-full, passed): `memory_context → USER.md: port 8081, tabs`, then the agent writes `listen 8081;` with tab indentation. |
| 7 | `7-trial-task18-skill.png` | Trial 18 (opencode-skills, passed): the skill is globbed, read, and applied. Same trial under Hermes never opens the skill and fails 5/5. |
| 8 | `8-nudge-control.png` | Nudge control experiment: `hermes-full` vs `hermes-nudge` — cost excludes 0, score does not. |
| 9 | `9-configs.png` | Configs page — immutable `name@vN`, feature badges, token budget / steps columns. |

To reproduce from a clean machine:

```bash
cp .env.example .env     # Azure creds
docker compose up --build
# wait ~1 min for worker health, then open http://localhost:3000
```
