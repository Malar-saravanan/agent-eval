# Agent Evals Platform — one-page brief

**Problem.** Agents ship as *harness × model × settings*. Any of the three can change. The platform answers, with evidence: did it get better, worse, or stay the same — and how sure are we?

**Stack.** NestJS (control plane, SQLite, REST), Vue 3 (UI), Python/FastAPI (worker). Docker-compose, one command to run.

---

## Architecture

```
Vue UI ─► NestJS API ─► Python worker
          (SQLite)       ├─ /trial              run one trial, grade, return trace + metrics
                         ├─ /v1/chat/completions   metering gateway ──► Azure OpenAI
                         ├─ harness adapters    Hermes, OpenCode
                         └─ graders             unit_tests | exact_match | fs_state | llm_judge
```

- **API owns state.** Configs, experiments, trials, queue, statistics, export. All in SQLite.
- **Worker is stateless.** Receives `{trial_id, task_id, config}`, returns a complete result (trace, usage, cost, grade).
- **One contract between them:** a single JSON schema.

### Load-bearing decisions

| Decision | Rationale |
|---|---|
| **Metering gateway in front of Azure** | Both harnesses speak OpenAI chat. Budgets, auth, parameter sanitisation, and cost accounting live in one place — not duplicated per adapter, not trusted to harness-reported numbers. |
| **Task is the unit of analysis, not the trial** | Trials within a task are repeated measures. Aggregate CIs are driven by task count; adding trials only sharpens individual tasks. Drives the paired hierarchical bootstrap. |
| **Platform failure ≠ agent failure** | A trial that OOM-killed, lost its connection, or hit a 429 cannot count against the agent. Status enum (`infra_error`, `grader_error`, `not_applicable`) is first-class; these are retried or excluded, never silently scored zero. |
| **Agents are untrusted** | Per-trial unprivileged uid, scrubbed env, root-only task directory, no-follow file reads in graders, hidden pytest runs outside the workdir, random per-trial gateway bearer. An audit of 1,124 tool calls found zero touches on hidden tests / solutions / keys. |
| **Configs are immutable** | Content-hashed `name@vN`. A result always points at the exact configuration that produced it. |
| **Adapters, not forks** | New harness = one file + one registry entry. New model = one YAML line. The core (queue, stats, UI) stays untouched. Verified by a regression test that runs a dummy third harness end-to-end. |

### Trade-offs taken

- **One container, not one container per trial.** Isolation is a per-trial uid inside the worker. Fine for cooperative models; a determined adversary sharing the kernel is out of scope.
- **Judge in the same family as the subject.** `gpt-4.1-mini` judges `gpt-4.1-mini` output. Self-preference risk is not neutralised. Mitigated by using the judge on only 3 of 20 tasks and reporting pooled agreement (79%, kappa 0.55) with human labels.
- **Hermes needs world-writable `installs/`.** Shared runtime; a hostile agent could tamper with it. Documented.
- **Conservative infra-error attribution.** If a `failed` trial coincides with any gateway error, it is reclassified `infra_error`. Can discard a real agent failure that happened during throttling. With 0 gateway errors in the final runs this had no measurable effect.

---

## In scope

- Hermes Agent (required) and OpenCode as harnesses.
- One Azure OpenAI model (`gpt-4.1-mini`); adding more is a YAML entry.
- 20 hand-authored tasks, mixed graders (unit tests, exact match, FS state, LLM judge).
- N repeated trials with isolation, budgets, retries, and heartbeats.
- Paired statistics (hierarchical bootstrap + McNemar) with explicit "within noise" and "insufficient data" verdicts.
- Per-trial trajectory inspection; JSON/CSV export; rule-based failure classification.
- 206 offline tests (151 worker, 55 API), including regression tests for every bug found during review.

## Out of scope

- **Second provider / open-weight model.** The brief asks for two; one was shipped by choice. Adding one is a `config/models.yaml` entry plus a deployment env var.
- **Adversarial sandboxing.** No per-trial container, no network sandbox. Cooperative models only.
- **Distributed scheduling, multi-tenant auth, SSO.** Single-operator local-first.
- **Live/streaming UI metrics.** Polling every 3s is enough at this scale.
- **Automated prompt-caching discount accounting.** Reported cost is an upper bound.
- **Judge metering attribution per trial.** Judge calls metered globally, not charged to the trial they graded (~$0.001 per judged trial).

## Extensible without touching core

- **Add a model** → `config/models.yaml` + `.env`. Zero code.
- **Add a harness** → subclass `Harness`, implement `run(ctx)`, register. ~50 lines.
- **Add a grader type** → one function + registry entry in `worker/graders.py`.
- **Add a failure category** → one rule in `api/src/failures.ts`; UI picks it up automatically.
- **Add a statistic** → `api/src/stats.ts`; the Compare endpoint composes.
- **Swap storage** → `api/src/db.ts` is the only consumer of `node:sqlite`.

---

## Results (see `docs/experiment.md`; screenshots in `docs/screenshots/`)

Main experiment: 20 tasks × 3 configs × N=5 = 290 scored trials, 0 infra errors, $4.36.

| config            | mean score (95% CI)   | notes |
|-------------------|-----------------------|-------|
| hermes-plain      | 0.765 [0.585, 0.922]  | baseline |
| hermes-full       | 0.770 [0.588, 0.930]  | skills + memory on; **Δ vs plain = +0.005 [−0.092, +0.108] — within noise** |
| opencode-skills   | 0.822 [0.667, 0.956]  | **Δ vs hermes-full = +0.011 [−0.178, +0.211] — within noise** |

Decisive per-task findings (replicated across two runs):

- **Memory works when the task needs it.** Task 19 (`memory-server-conf`): plain 0.00 → full 0.80, CI [+0.40, +1.00]. Trace shows `memory_context → USER.md: port 8081, tabs`; the agent writes `listen 8081;`.
- **Harnesses diverge on skill discovery.** Task 18 (`lint-rules-skill`): OpenCode opens the skill in 5/5 trials and passes 4/5; Hermes opens it in 0/5 and passes 0. Same model, same skill files, opposite behaviour.
- **Aggregate parity hides opposing per-task effects.** Hermes wins CSV (06), OpenCode wins log-counting (11) — each with mechanistic trace evidence.

Nudge control (`hermes-full` + "check your skills and memory first"): behaviour changes (`capability_unused` 10 → 3), cost rises (+$0.012/trial, +29.6k tokens), scores barely move. The ceiling is the model, not the harness.

---

## Known limits (summary — full list in `docs/limits.md`)

- 20 tasks; 11 saturate at 1.00. Aggregate CI resolves effects ≥ ~0.10.
- One model, one provider. Harness ranking is confounded with model fit.
- Judge-scored tasks (3 of 20) are noisier than deterministic graders.
- Task 19 was reworded after observing failure — disclosed.
- Sandbox is for cooperative agents, not adversarial ones.

---

## How to verify

```bash
cp .env.example .env         # Azure credentials
docker compose up --build    # UI + API on :3000 (or API_PORT)
# Configs → create → Experiments → Start → open to see Compare + trajectories
```

- Tests: `cd api && npm test` (55), `cd worker && pytest tests -q` (151), `python tasks/validate.py` (20/20 green).
- Repo entry points: [`README.md`](../README.md), [`docs/design.md`](design.md), [`docs/experiment.md`](experiment.md), [`docs/limits.md`](limits.md), [`docs/cost.md`](cost.md).
