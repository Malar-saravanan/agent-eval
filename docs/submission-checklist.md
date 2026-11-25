# Requirements → evidence

**Legend.** done · partial · open.

## Platform

| Requirement | Status | Where |
|---|---|---|
| Evaluate any harness × any model | done | `worker/harnesses.py`, `config/models.yaml`, `docs/design.md` |
| Required harness: Hermes Agent | done | `Hermes` adapter — headless `hermes chat --format stream-json` |
| Second harness | done | `OpenCode` adapter — distinct CLI, event format, skill mechanism, no persistent memory |
| Two models from different providers (or one open-weight) | open | one Azure deployment (`gpt-4.1-mini`). Adding a model is one YAML entry plus a deployment env var. Deferred by choice. |
| New harness / model is an adapter, not a core change | done | regression test registers a dummy third harness and runs it end to end without touching core code (`worker/tests/test_adapters.py`) |
| Deterministic graders | done | `unit_tests`, `exact_match`, `fs_state` (`worker/graders.py`) |
| LLM-as-judge with rubric | done | `llm_judge` — binary rubric criteria, JSON, temperature 0, output delimited as untrusted |
| Judge trustworthiness checked | done | 30 human labels; agreement 79%, kappa 0.55; `docs/judge-validation.md` |
| Configurations = harness × model × settings, versioned, reproducible | done | immutable `name@vN` with content hash; per-trial `meta` records harness version, deployment, resolved model snapshot, task hash, budgets |
| N repeated trials per task per config | done | `trials` per experiment (default 5) |
| No state leaks between trials (unless memory says so) | done | fresh workdir + harness home + exclusive unprivileged uid; tasks root-only; verified by probe and audit |
| Timeouts, rate limits, retries, partial failures | done | per-task timeout; infra errors retried (3 attempts, backoff) and excluded; grader errors excluded; crash-safe queue resume |
| Step and token budgets | done | enforced in the metering gateway for every harness |
| Comparison with confidence (CIs + paired test) | done | hierarchical paired bootstrap plus McNemar's exact test (`api/src/stats.ts`) |
| Per-task deltas, "noise" visible | done | Compare view: forest plot, within-noise / insufficient-data banners |
| Cost, latency, tokens next to quality | done | Summary and Compare |
| Trajectory inspection | done | Trial view — messages, tool calls and results, memory reads/writes, skill use, grader reasoning, final score |
| Failure analysis (stretch) | done | nine rule-based categories, per-config table (`api/src/failures.ts`) |
| Runs locally with one command, keys via `.env` | done | `docker compose up --build`, `.env.example` |
| Sample task set (≥ 20, mixed graders, some discriminating) | partial | 20 tasks, four grader types, four skill/memory tasks. Discrimination is limited: 11/20 saturate at 1.00; of the four feature tasks only 19 separates configurations (see `experiment.md`). |
| Results persisted and exportable | done | SQLite; JSON and CSV export |
| Assumptions documented | done | `docs/design.md` (Assumptions), `docs/limits.md` |

## Deliverables

| # | Deliverable | Status | Where |
|---|---|---|---|
| 1 | Source in Git, tested, README (setup, add task / harness / model) | done | repo initialised; 151 worker + 55 API tests |
| 2 | Design document | done | `docs/design.md` |
| 3 | Known limits | done | `docs/limits.md` |
| 4 | Cost estimate (formula, actual, reductions) | done | `docs/cost.md` |
| 5 | One real experiment (hypothesis, N, CIs, trajectories, conclusion) | done | `docs/experiment.md` — hypothesis stated pre-run; one disclosed post-hoc rewording |
| 6 | Video (≤ 10 min) | open | script in `docs/demo-script.md` |

## Evaluation axes

| Area | Evidence |
|---|---|
| Methodology | task as unit of analysis; paired hierarchical bootstrap; honest within-noise verdicts; judge validated and its weakness stated; infra failures never scored; invalid runs disclosed |
| Abstraction | `Harness` / model-registry adapters; one metering gateway for every harness; new-harness regression test |
| Observability | normalised event stream (messages, tool calls, skills, memory, errors, grade); per-trial provenance metadata; failure categories |
| Engineering quality | 206 offline tests; sandbox, reaping, budget, and classification regressions pinned by tests; one-command boot |
| Judgment | scope cuts and limits stated; bugs found by investigating surprising numbers and disclosed with their costs |

## Open items

1. **Second model.** Required by the brief; deferred by choice. Enable with a `config/models.yaml` entry and a deployment env var.
2. **Video.** Record from `docs/demo-script.md`.
3. **Pre-submission clean-clone check.** `docker compose up --build` from a fresh clone, create configs, launch a 1-trial experiment. Last performed on the final commit.
