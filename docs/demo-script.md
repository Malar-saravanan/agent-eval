# Demo video script

Target 8–9 minutes, hard limit 10.

**Pre-flight.** `docker compose up -d`. Wait ~1 minute for the worker to warm up. Open the finished MAIN experiment in a second tab — do **not** run a 300-trial experiment live (~25 min).

| Time | Show | Narration |
|------|------|-----------|
| 0:00 | Terminal `docker compose up`, then the UI | "One command. NestJS control plane, a Python worker that runs the harnesses, and a Vue UI." |
| 0:30 | `docs/design.md` architecture diagram | "Harnesses and models are adapters. Both harnesses reach Azure through one metering gateway — that is where budgets, authentication, and cost accounting live." |
| 1:30 | Configs page; create a config live | "A config is harness × model × settings — skills, memory, temperature, step and token budgets, nudge. Configs are content-hashed and immutable; saving a change produces `name@v2`." |
| 2:30 | Experiments page; start a small run (2 configs, 3 tasks, N=2) | "Every task runs under every config, N times, each in a fresh workdir and home as an unprivileged user. Infrastructure failures are retried and excluded from scoring." |
| 3:30 | Open the finished MAIN experiment → Summary | "Mean score with bootstrap CI per config, plus cost, latency, and tokens. Zero infra errors across 300 trials." |
| 4:15 | Compare — hermes-plain vs hermes-full | "Paired by task, hierarchical bootstrap. The CI spans zero; the platform reports *within noise* and will not call a winner it cannot support." Point at per-task deltas and the forest plot. |
| 5:15 | Compare — hermes-full vs opencode-skills | "Aggregate also within noise, but per-task deltas show real, opposing effects: Hermes wins CSV, OpenCode wins log counting and the skill task. The aggregate alone would hide this." |
| 6:00 | Failure analysis table | "Failures are grouped by cause — `capability_unused`, `hallucinated_tool_args`, `wrong_answer`. A regression points straight at a reason." |
| 6:45 | Click into a failed trial (task 18 or 11) | "Full trajectory — messages, tool calls, memory reads and writes, skill use, grader reasoning, final score. Hermes never opens the skill here; the lint rules go unapplied." Mention the meta line: harness version, resolved model, task hash, budgets. |
| 8:00 | The nudge control | "A positive control: with one extra sentence the agent consults its skills, `capability_unused` drops — but scores barely move. The limit is the model, not the harness or the suite." |
| 8:45 | `docs/limits.md`, `docs/cost.md` | "Known limits and roughly $4.6 per 300-trial experiment. End." |

**Technical.** Browser at 1280px, dark mode off, zoom 110%. Pre-load the trial page. Do not show `.env`.
