# Assignment requirements -> evidence

Status key: **done**, **partial** (works, with a stated gap), **open** (not done).

## Platform

| Requirement | Status | Where |
|---|---|---|
| Evaluate any harness X with any model Y | done | `worker/harnesses.py` (adapters), `config/models.yaml` (models), `docs/design.md` |
| Required harness: Hermes Agent | done | `Hermes` adapter, headless `hermes chat --format stream-json` |
| A second harness | done | `OpenCode` adapter (different CLI, event format, skill mechanism, no memory) |
| Two models from different providers, or one open-weight model | **open (by decision)** | one Azure deployment (`gpt-4.1-mini`); the brief asks for two, which was deferred. Adding a model = one YAML entry + `MODELn_DEPLOYMENT` |
| New harness/model = adapter, not core change | done | demonstrated by a test that adds a dummy third harness with zero other changes (`worker/tests/test_adapters.py`); README "Add a harness / model" |
| Tasks + scoring: deterministic graders | done | `unit_tests`, `exact_match`, `fs_state` (`worker/graders.py`) |
| Tasks + scoring: LLM-as-judge with rubric | done | `llm_judge`, binary rubric criteria, JSON, temp 0 |
| Judge trustworthiness checked | done (moderate) | 30 human labels, agreement 79%, kappa 0.55; weak on counting/whitespace criteria. `docs/judge-validation.md`. Judge is the same model family as the subject (disclosed) |
| Configurations = harness x model x settings, versioned, reproducible | done | immutable `name@vN`, hash; settings: skills, memory, temperature, max steps, token budget, nudge. Per-trial `meta` (harness version, deployment, resolved model snapshot, task hash, budgets) |
| N repeated trials per task per config | done | `trials` per experiment (default 5) |
| Isolation: no state leaks between trials unless memory says so | done | fresh workdir + harness home + unprivileged uid per trial; hidden tests/solutions root-only; verified by probe and audit (`design.md`) |
| Timeouts, rate limits, retries, partial failures without corrupting results | done | per-task timeout; gateway passes 429/5xx through; infra errors retried (3 attempts, backoff) and excluded, never scored; grader errors excluded; crash-safe resume. Tested (`api/src/runner.spec.ts`, `worker/tests/test_trial.py`) |
| Step and token budgets | done | enforced in the gateway for every harness (`worker/meter.py`) |
| Comparison with confidence: CIs + paired test | done | hierarchical paired bootstrap + McNemar (`api/src/stats.ts`, 8 tests) |
| Per-task deltas, "noise" made obvious | done | compare view: forest plot, "within noise" banner |
| Cost, latency, token usage next to quality | done | summary + compare |
| Run inspection: full trajectory incl. memory/skills, grader reasoning, score | done | trial view; Hermes memory reads shown via injected `memory_context` event; skill reads via skill-read tool calls |
| Failure analysis (stretch) | done | 9 rule-based categories, per-config table (`api/src/failures.ts`) |
| Runs locally with one command, keys via `.env` | done | `docker compose up --build`; `.env.example` |
| Sample task set >= 20, mixed graders, some that tell configs apart | partial | 20 tasks, 4 grader types, 4 skill/memory tasks. Discriminating power is limited: 11/20 saturate at 1.00; of the 4 feature tasks only task 19 separates configs (see `experiment.md`) |
| Results persisted and exportable | done | SQLite; JSON/CSV export |
| Document every assumption | done | `docs/design.md` (Assumptions), `docs/limits.md` |

## Deliverables

| # | Deliverable | Status | Where |
|---|---|---|---|
| 1 | Source in Git, production-grade, tested, README (setup, add task/harness/model) | done | code + README; 151 worker + 55 API tests; git repository initialised |
| 2 | Design doc (architecture, adapters, data model, isolation/repro, graders + validation, stats + N) | done | `docs/design.md` |
| 3 | Known limits | done | `docs/limits.md` (18 items) |
| 4 | Cost estimate: formula + actual + reduction | done | `docs/cost.md` |
| 5 | One real experiment: hypothesis, setup/N, CIs, 2-3 trajectories, conclusion | done | `docs/experiment.md` (hypothesis stated before the run; one disclosed post-hoc task rewording) |
| 6 | Video <= 10 min | **open** | script in `docs/demo-script.md` |

## What evaluators look for

| Area | Evidence |
|---|---|
| Eval methodology | task as the unit of analysis; paired hierarchical bootstrap; honest "within noise" verdicts; judge validated and its weakness stated; infra failures never scored; invalid runs discarded and disclosed |
| Abstraction | `Harness` / model-registry adapters, one metering gateway for every harness, new-harness test |
| Observability | normalized trace (messages, tool calls/results, skills, memory read/write, errors, grade), per-trial provenance metadata, failure categories |
| Engineering quality | 206 offline tests, reaping/sandboxing/budget regressions pinned by tests, one-command boot |
| Judgment | scope cuts and limits stated; two real bugs found by checking surprising numbers, not by accepting them |

## Open items (need you)

1. **Second model** (required by the brief): give me another deployment name (and endpoint/key if different), I add it to `config/models.yaml` and run a model-comparison experiment (same harness, two models) so the second-model requirement is met with evidence.
2. **Video**: record using `docs/demo-script.md`.
3. **Second model** (see above) is the only functional gap; the clean-clone check (fresh volumes, README steps) was done on an earlier build and should be repeated once more before submitting: `docker compose up --build`, create configs, run a 1-trial experiment.
