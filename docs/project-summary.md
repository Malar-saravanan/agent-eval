# Agent Evals Platform — project summary

**Problem.** Agents ship as *harness × model × settings*. Any of the three can change. The platform answers, with evidence, whether a change made the agent better, worse, or the same — and how confident we are.

**Stack.** NestJS control plane (SQLite, REST), Vue 3 UI, Python / FastAPI worker. One Docker command to run.

---

## High-level design

```
┌──────────────┐      REST        ┌────────────────────┐      HTTP       ┌──────────────────────────┐      HTTPS       ┌───────────────┐
│              │ ───────────────► │                    │ ──────────────► │                          │ ───────────────► │               │
│   Vue  UI    │                  │     NestJS API     │                 │     Python  Worker       │                  │  Azure OpenAI │
│              │ ◄─────────────── │   (SQLite, state)  │ ◄────────────── │ (stateless, per-request) │ ◄─────────────── │               │
└──────────────┘  polling 3 s     └────────────────────┘                 └──────────────────────────┘                  └───────────────┘
                                    │  configs           │ /trial           │ sandbox + harness adapter
                                    │  experiments       │ /v1/chat/...     │ metering gateway
                                    │  trial queue       │                  │ grader
                                    │  statistics        │                  │
                                    │  export JSON/CSV   │                  │
```

Four distinct responsibilities, three HTTP hops, one JSON contract between API and worker. The API owns *all* state. The worker is stateless — every call carries everything it needs.

### Component responsibilities

| Component   | Owns                                                                          | Does not own                          |
|-------------|-------------------------------------------------------------------------------|---------------------------------------|
| **UI**      | Rendering, polling, URL-based navigation                                       | Statistics, auth, mutation ordering    |
| **API**     | Configs, experiments, trials, queue + retries, bootstrap statistics, exports   | Model calls, sandboxing, grading       |
| **Worker**  | Harness adapters, metering gateway, graders, trial sandbox, usage accounting   | Persistence, scheduling                |
| **Azure**   | Model inference                                                                | Everything else                        |

---

## Trial lifecycle (swimlane)

One trial, from "launch experiment" in the UI to a persisted row with full trace.

```
         UI              NestJS API                       Python Worker                         Azure OpenAI
         │                   │                                 │                                    │
 launch  ├──POST experiments─►                                 │                                    │
         │                   │ validate, dedupe,               │                                    │
         │                   │ create N trial rows             │                                    │
         │                   │ status = queued                 │                                    │
         │                   │                                 │                                    │
         │                   │ trial queue (concurrency = 4)   │                                    │
         │                   │ take 1 trial                    │                                    │
         │                   │                                 │                                    │
         │                   ├─POST /trial + worker-token─────►│                                    │
         │                   │                                 │ allocate exclusive uid              │
         │                   │                                 │ create /runs/<id>/{work,home}       │
         │                   │                                 │ chown, chmod 700                    │
         │                   │                                 │ issue per-trial gateway secret      │
         │                   │                                 │                                    │
         │                   │                                 │ invoke harness CLI as uid          │
         │ UI polls summary  │                                 │   ├─ seed session (if memory on)    │
         │ /trials /failures │                                 │   │   ├─ POST /v1/chat/completions─►│
         │ every 3 s         │                                 │   │   │     auth: Bearer <secret>   │
         │                   │                                 │   │   │     ◄──── chat response ────┤
         │                   │                                 │   │   │     meter tokens, cost     │
         │                   │                                 │   │   │     check step/token budget │
         │                   │                                 │   │   └─ repeat until done          │
         │                   │                                 │   │                                │
         │                   │                                 │   └─ task session (same shape)      │
         │                   │                                 │                                    │
         │                   │                                 │ invoke grader as uid               │
         │                   │                                 │   (hidden tests run root-owned,     │
         │                   │                                 │    outside the workdir)             │
         │                   │                                 │                                    │
         │                   │                                 │ release gateway secret              │
         │                   │                                 │ reap uid processes                 │
         │                   │                                 │ delete /runs/<id>/                  │
         │                   │                                 │                                    │
         │                   │◄─────── trial result ───────────┤                                    │
         │                   │ store status, score, usage,     │                                    │
         │                   │ events, trace, meta             │                                    │
         │                   │                                 │                                    │
         │                   │ if status == infra_error:       │                                    │
         │                   │   retry (max 3, backoff)        │                                    │
         │                   │                                 │                                    │
         │ UI reads summary, │                                 │                                    │
         │ compare, trials   │                                 │                                    │
         │◄─── statistics ───┤ compute on demand               │                                    │
```

Infrastructure failure (worker killed, upstream 429, grader crash) is retried and never attributed to the agent. The whitespace heartbeats from `/trial` keep the response open for the ~20-minute budget without triggering a duplicate retry from Node.

---

## Isolation boundaries (low-level)

Two principals share a host kernel and the worker container's network: the *worker process* (root) and the *agent* (per-trial unprivileged uid, running inside the worker container). The agent can execute arbitrary shell and must not be able to reach anything that would let it cheat or exfiltrate credentials.

```
                             worker container
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                      │
│   worker process (root, uid = 0)                       agent  (uid = 2xxxx)          │
│   ┌─────────────────────────────────────────┐         ┌───────────────────────────┐  │
│   │  /srv/tasks            mode 700         │   ✗     │                           │  │
│   │  hidden tests, solutions                │ ─────── │                           │  │
│   │  Azure key in env                       │   ✗     │                           │  │
│   │  /ipc/worker-token     mode 600         │ ─────── │                           │  │
│   │  reads other trial dirs                 │   ✗     │                           │  │
│   │                                         │ ─────── │                           │  │
│   │                                         │         │  /runs/<id>  mode 700     │  │
│   │                                         │   ✓     │  own workdir and home     │  │
│   │                                         │ ───────►│  write, execute           │  │
│   │                                         │   ✓     │  /opt/cache  (shared)     │  │
│   │                                         │ ───────►│  harness binaries         │  │
│   │                                         │         │                           │  │
│   │  /v1/chat/completions                   │   ✓     │  per-trial bearer secret  │  │
│   │  requires per-trial bearer secret       │◄────────│  (issued at trial start,  │  │
│   │                                         │         │   released at end)        │  │
│   │                                         │         │                           │  │
│   │  POST /trial                            │   ✗     │                           │  │
│   │  requires worker-token (API only)       │ ────────│                           │  │
│   └─────────────────────────────────────────┘         └───────────────────────────┘  │
│                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Verified live: an unprivileged uid gets 401 on `/trial` with or without a wrong token, 401 on `/v1/chat/completions` with or without a forged bearer, and `Permission denied` on `/srv/tasks` and `/ipc/worker-token`. An integrity audit of 1,124 real tool calls found zero touches on hidden tests, solutions, keys, or other trials.

---

## Status classification (low-level)

Every trial resolves to exactly one of seven statuses. Statistics use only `passed`, `failed`, and `timeout` — the rest are explicitly excluded. This is the decision tree:

```
            trial outcome
                 │
        ┌────────┴─────────┐
        │  harness ran     │
        │  harness failed  │
        └────────┬─────────┘
                 │
      ┌──────────┴──────────────┬───────────────────────┬────────────────────────┐
      │                         │                       │                        │
  no output                 timed out              completion marker         requirement
  OR exit < 0               past limit             missing + exit ≠ 0        mismatch
  OR lost connection                                                         (harness lacks
      │                         │                       │                     capability)
      ▼                         ▼                       ▼                        │
 infra_error              timeout, score 0         infra_error                   ▼
 retried 3x               (agent outcome)                                   not_applicable
                                │                                           (excluded)
                                │
                                ▼
                     ┌──────────┴──────────┐
                     │ run grader          │
                     └──────────┬──────────┘
                                │
              ┌─────────────────┼─────────────────────────┐
              │                 │                         │
         grader crashed    tests passed             tests failed
         or definition     + summary matches        or output wrong
         broken                │                         │
              │                ▼                         ▼
              ▼           passed, score ≥ 0.75       failed
         grader_error     + grade event appended     + grade event appended
         (excluded)
                                                  │
                                          any gateway error
                                          during the trial?
                                                  │
                                                yes│
                                                  ▼
                                            reclassify infra_error
                                            (conservative: a throttled
                                             trial may not be the agent's
                                             fault)
```

A passing trial is never downgraded. Budget exhaustion is the agent's outcome and is graded normally — the trace still carries the `budget_exhausted` event.

---

## Data model (low-level)

Three tables, SQLite, one unique constraint prevents duplicate trial cells.

```
┌─────────────────────────┐          ┌───────────────────────────┐          ┌─────────────────────────────┐
│ configs                 │          │ experiments               │          │ trials                      │
├─────────────────────────┤          ├───────────────────────────┤          ├─────────────────────────────┤
│ id          PK          │◄─┐       │ id              PK        │◄─┐       │ id              PK          │
│ name                    │  │       │ name                      │  │       │ experiment_id   FK ─────────┤
│ version     INT         │  └───────┤ config_ids      JSON[]    │  └───────┤ config_id       FK ─────────┤
│ hash        12 hex      │          │ task_ids        JSON[]    │          │ task_id                     │
│ harness                 │          │ trials_per_task INT       │          │ trial_idx                   │
│ model                   │          │ created_at                │          │ status          enum(7)     │
│ settings    JSON        │          └───────────────────────────┘          │ score           REAL?       │
│ created_at              │                                                 │ reasoning                   │
└─────────────────────────┘                                                 │ duration_ms                 │
                                                                            │ cost_usd                    │
   immutable:                                                               │ usage           JSON        │
   edit settings → new                                                      │ final_text                  │
   name@vN with new hash                                                    │ files           JSON        │
                                                                            │ events          JSON        │
   trials row carries full                                                  │ meta            JSON        │
   provenance so results                                                    │ attempts                    │
   survive config edits                                                     ├─────────────────────────────┤
                                                                            │ UNIQUE (experiment_id,      │
                                                                            │   config_id, task_id,       │
                                                                            │   trial_idx)                │
                                                                            └─────────────────────────────┘

   meta: harness_version, model_deployment, model_resolved (actual Azure snapshot id),
         task_hash (fixture + tests + skills), budget{max_steps, max_tokens}, nudge, uid
```

Every trial row is self-describing: given the row alone, we can state which harness version, which model snapshot, which task content hash, and which budget produced it. Config edits do not retroactively change past results.

---

## Load-bearing decisions

| Decision | Rationale |
|---|---|
| **Metering gateway in front of Azure** | Both harnesses speak OpenAI chat. Budgets, auth, parameter sanitisation, and cost accounting live in one place — not duplicated per adapter, not trusted to harness-reported numbers. |
| **Task is the unit of analysis, not the trial** | Trials within a task are repeated measures. Aggregate CIs are driven by task count; adding trials only sharpens individual tasks. Drives the paired hierarchical bootstrap. |
| **Platform failure ≠ agent failure** | A trial that OOM-killed, lost its connection, or hit a 429 cannot count against the agent. Status enum is first-class; these are retried or excluded, never silently scored zero. |
| **Agents are untrusted** | Per-trial unprivileged uid, scrubbed env, root-only task directory, no-follow file reads in graders, hidden pytest runs outside the workdir, random per-trial gateway bearer. |
| **Configs are immutable** | Content-hashed `name@vN`. A result always points at the exact configuration that produced it. |
| **Adapters, not forks** | New harness = one file + one registry entry. New model = one YAML line. Core stays untouched. Verified by a regression test running a dummy third harness end-to-end. |

## Trade-offs

- **One container, not one per trial.** Isolation is a per-trial uid inside the worker. Fine for cooperative models; a determined adversary sharing the kernel is out of scope.
- **Judge in the same family as the subject.** `gpt-4.1-mini` judges `gpt-4.1-mini` output. Self-preference risk is not neutralised. Mitigated by using the judge on only 3 of 20 tasks; pooled agreement with human labels is 79%, kappa 0.55.
- **Hermes needs world-writable `installs/`.** Shared runtime; a hostile agent could tamper with it. Documented.
- **Conservative infra-error attribution.** If a `failed` trial coincides with any gateway error, it is reclassified `infra_error`. Can discard a real agent failure that happened during throttling. With 0 gateway errors in the final runs this had no measurable effect.

---

## In scope / out of scope

**In scope.** Hermes + OpenCode as harnesses; one Azure model (`gpt-4.1-mini`); 20 hand-authored tasks across four grader types; N repeated trials with isolation, budgets, retries, and heartbeats; paired statistics with explicit "within noise" / "insufficient data" verdicts; per-trial trajectory inspection; JSON/CSV export; rule-based failure classification; 206 offline tests.

**Out of scope.** Second provider / open-weight model (shipped as a single-YAML extension point); adversarial sandboxing (per-trial container or VM); distributed scheduling; multi-tenant auth; automated prompt-caching discount accounting; per-trial attribution of judge cost.

## Extension points

- **Add a model** → `config/models.yaml` + `.env`. Zero code.
- **Add a harness** → subclass `Harness`, implement `run(ctx)`, register. ~50 lines.
- **Add a grader type** → one function + registry entry in `worker/graders.py`.
- **Add a failure category** → one rule in `api/src/failures.ts`; UI renders it automatically.
- **Add a statistic** → `api/src/stats.ts`; the Compare endpoint composes.
- **Swap storage** → `api/src/db.ts` is the only consumer of `node:sqlite`.

---

## Results

Main experiment: 20 tasks × 3 configs × N = 5 = 290 scored trials, 0 infra errors, $4.36. Raw exports in [`docs/results/`](results/); narrative in [`docs/experiment.md`](experiment.md); screenshots in [`docs/screenshots/`](screenshots/).

| config            | mean score (95% CI)   | notes |
|-------------------|-----------------------|-------|
| hermes-plain      | 0.765 [0.585, 0.922]  | baseline |
| hermes-full       | 0.770 [0.588, 0.930]  | skills + memory on; Δ vs plain = **+0.005 [−0.092, +0.108]** — within noise |
| opencode-skills   | 0.822 [0.667, 0.956]  | Δ vs hermes-full = **+0.011 [−0.178, +0.211]** — within noise |

Decisive per-task findings, replicated across two independent runs:

- **Memory works when the task requires it.** Task 19: plain 0.00 → full 0.80, CI [+0.40, +1.00]. Trace shows `memory_context → USER.md: port 8081, tabs`; the agent then writes `listen 8081;`.
- **Harnesses diverge on skill discovery.** Task 18: OpenCode opens the skill in 5/5 trials and passes 4/5; Hermes opens it in 0/5 and passes 0. Same model, same skill files, opposite behaviour.
- **Aggregate parity hides opposing per-task effects.** Hermes wins CSV (06); OpenCode wins log-counting (11). Each has mechanistic trace evidence.

Positive control (`hermes-full` + "check your skills and memory first"): behaviour changes measurably (`capability_unused` 10 → 3), cost rises (+$0.012/trial, +29.6k tokens), scores barely move. The ceiling is the model, not the harness.

---

## Known limits (headline — full list in [`docs/limits.md`](limits.md))

- 20 tasks; 11 saturate at 1.00. Aggregate CI resolves effects ≥ ~0.10.
- One model, one provider. Harness ranking is confounded with model fit.
- Judge-scored tasks (3 of 20) are noisier than deterministic graders.
- Task 19 was reworded after observing an initial failure — disclosed.
- Sandbox is for cooperative agents, not adversarial ones.

---

## How to verify

```bash
cp .env.example .env         # Azure credentials
docker compose up --build    # UI + API on :3000 (override with API_PORT)
# Configs → create → Experiments → Start → open to see Compare + trajectories
```

- Tests: `cd api && npm test` (55); `cd worker && pytest tests -q` (151); `python tasks/validate.py` (20/20 green).
- Reference reading, in order: [`README.md`](../README.md) → this file → [`docs/design.md`](design.md) → [`docs/experiment.md`](experiment.md) → [`docs/limits.md`](limits.md) → [`docs/cost.md`](cost.md).
- Raw exports: [`docs/results/`](results/). Screenshots: [`docs/screenshots/`](screenshots/).
