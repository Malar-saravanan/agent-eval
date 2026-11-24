# Demo video script (target 8-9 min, hard limit 10)

Pre-flight: `docker compose up -d`, wait until the worker is healthy (~1 min after boot for the warm-up), have the finished MAIN experiment open in a second tab (a full 300-trial run takes ~25 min, so do **not** run it live).

| Time | Show | Say |
|---|---|---|
| 0:00 | Terminal: `docker compose up`, then the UI | "One command. A NestJS control plane, a Python worker that runs the harnesses, and this Vue UI." |
| 0:30 | `docs/design.md` architecture diagram | "Harnesses and models are adapters. Both harnesses talk to one metering gateway, so tokens, cost and latency are measured the same way. Budgets and the sandbox live there too." |
| 1:30 | **Configs** page | "A config is harness x model x settings: skills, memory, temperature, step and token budgets, nudge. Configs are immutable and hashed: saving a change creates `name@v2`." Create a new config live (e.g. `hermes-memory-on`, memory + skills). |
| 2:30 | **Experiments** page: start a small one (2 configs, 3 tasks, N=2) | "Every task runs under every config, N times, each in a fresh workdir, home and unprivileged user. Infra failures are retried and never scored as a failure." Watch progress while talking. |
| 3:30 | Open the finished MAIN experiment: **Summary** | "Mean score with a bootstrap CI per config, plus cost, latency, tokens. Note 0 infra errors." |
| 4:15 | **Compare**: hermes-plain vs hermes-full | "Paired by task, hierarchical bootstrap. The CI spans zero, so the platform says *within noise*: it will not call a winner I can't support." Point at per-task deltas and the forest plot. |
| 5:15 | **Compare**: hermes-full vs opencode-skills | "Overall also noise, but per-task deltas show real, opposite effects: Hermes wins CSV, OpenCode wins the log count and the skill task. An aggregate alone would hide that." |
| 6:00 | **Failure analysis** table | "Failures are grouped by cause: `capability_unused`, `hallucinated_tool_args`, `wrong_answer`... so a regression points at a reason." |
| 6:45 | Click a **failed trial** (task 18 or 11) | "Full trajectory: messages, tool calls and results, memory reads and writes, skill use, grader reasoning, final score. Here Hermes never opened the skill, so the lint rules were never applied." Show the meta line (harness version, resolved model, task hash, budgets). |
| 8:00 | Positive-control experiment (nudge) | "To check the platform *can* see a feature helping, I added a nudge config: agents then consult skills, `capability_unused` drops, yet scores barely move, so the limit is the model, not the harness or the tasks." |
| 8:45 | `docs/limits.md`, `docs/cost.md` headings | "Known limits and cost per experiment: ~$4.6 for 300 trials." Stop. |

Tips: keep the browser at 1280px wide, dark mode off, zoom 110%. Pre-load the trial page. Do not show `.env`.
