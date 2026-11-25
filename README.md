# Agent Evals Platform

A platform for comparing agent configurations — any **harness** paired with any **model** — against a shared task set, with paired statistics, full trajectories, and honest handling of infrastructure failure.

Shipped harnesses: **Hermes Agent**, **OpenCode**. Shipped models: Azure OpenAI deployments (`gpt-4.1-mini`). Additional harnesses and models are adapters, not core changes.

---

## Run

```bash
cp .env.example .env            # Azure endpoint, key, API version, deployment name
docker compose up --build
# UI + API served from http://localhost:3000  (override with API_PORT in .env)
```

Requirements: Docker with ≥ 6 GB of memory and an Azure OpenAI chat deployment that supports tool-calling. First boot builds the worker image (installs Hermes and OpenCode; ~3 min) and warms the harness runtime (~1 min). Subsequent boots are near-instant.

### Workflow

1. **Configs** — define a configuration as `harness × model × settings` (skills, memory, temperature, step budget, token budget, nudge). Configs are content-hashed and immutable; editing an existing name produces a new version.
2. **Experiments** — pick configs, tasks, and trials-per-task; launch. The queue runs trials concurrently, retries infrastructure failures, and never attributes platform failure to the agent.
3. **Analyse** — the experiment page reports mean scores with bootstrap CIs, paired comparisons with per-task deltas and a forest plot, cost/latency/tokens alongside quality, and failure classification. Per-trial trajectories are inspectable. Exports in JSON and CSV.

### Reproducing the reported experiment

Create the four configs below (model `gpt-4.1-mini`), then launch an experiment over the first three, all tasks, N=5 (~25 min, ~$4.4):

| name              | harness   | skills | memory | nudge |
|-------------------|-----------|--------|--------|-------|
| `hermes-plain`    | hermes    | off    | off    | off   |
| `hermes-full`     | hermes    | on     | on     | off   |
| `opencode-skills` | opencode  | on     | n/a    | off   |
| `hermes-nudge`    | hermes    | on     | on     | on    |

The nudge control runs against `hermes-full` on tasks 02, 11, 14, 17–20.

Defaults: temperature 0.2, 30 steps, 300k tokens per trial. A **step** is a model call that offers tools; budgets are enforced centrally in the gateway for every harness.

---

## Layout

```
api/      NestJS control plane — configs, experiments, trial queue, stats, export (SQLite via node:sqlite). Serves the built UI.
web/      Vue 3 + TypeScript UI (Vite).
worker/   Python / FastAPI — metering model gateway, harness adapters, graders, trial runner.
tasks/    Task definitions (task.yaml + fixture/ + hidden tests/ + skills/).
config/   Model registry and prices.
docs/     project-summary (1-page brief), design, experiment, cost, limits, judge-validation, api.
```

---

## Extending

**Add a task.** Create `tasks/<id>/task.yaml` with a prompt, requirements, optional setup (skills, memory seed), a grader, and limits. Place starting files under `fixture/`. Tasks are copied into a root-only directory at worker boot — restart the worker after editing. Run `python tasks/validate.py` to confirm the untouched fixture fails and the reference `solution/` passes.

```yaml
id: 21-my-task
title: ...
category: code            # code | fs | exact | judge | skill | memory
prompt: |
  ...
requires: []              # [skills] and/or [memory]; harnesses without the capability return not_applicable
setup: {skills: [name], memory_seed: "prior-session message"}
grader:
  type: unit_tests        # hidden tests copied in AFTER the run
  # type: exact_match     # expected: "42", source: final_answer | file:answer.txt
  # type: fs_state        # [{file_exists}, {file_contains}, {yaml_eq}, ...]
  # type: llm_judge       # rubric, files
limits: {timeout_s: 240, max_turns: 20}
```

**Add a model.** An entry in `config/models.yaml` (deployment env var and prices) plus the env var in `.env`. The gateway maps model name → Azure deployment, injects `api-version` and `api-key`, strips parameters Azure rejects, and records tokens, latency, and cost. No harness or UI change required.

**Add a harness.** Subclass `Harness` in `worker/harnesses.py`: declare `name` and `capabilities`, implement `run(ctx) → Result` by invoking the CLI against `GATEWAY_URL` with the per-trial secret as its API key, and translate native output into the common event stream (`assistant`, `tool_call`, `tool_result`, `error`). Register in `HARNESSES` and in `api/src/catalog.ts`. The existing adapters are ~50 lines each; the queue, graders, stats, and UI remain untouched.

---

## Tests

```bash
cd api    && npm ci && npm test                                                   # 55 tests
cd worker && pip install -r requirements.txt \
           && MODELS_FILE=../config/models.yaml python -m pytest tests -q         # 151 tests (4 skipped off-Linux)
python tasks/validate.py                                                          # every task fails untouched, passes with reference solution
```

Tests are offline — no Azure calls, no harness binaries. Inside the running stack: `docker compose exec worker python -m pytest tests -q`.

---

## Design in one paragraph

A NestJS control plane persists configs, experiments, and trials in SQLite and schedules work. A Python worker runs each trial as its own unprivileged user inside a fresh directory; Hermes and OpenCode reach Azure only through a metering gateway that enforces step and token budgets and records usage uniformly. Graders score the result against hidden tests, file-system state, exact match, or an LLM rubric. The API computes paired bootstrap statistics, classifies failures by cause, and exposes everything over REST. Infrastructure failures are retried and excluded from scoring; they are never attributed to the agent.

See [`docs/design.md`](docs/design.md), [`docs/experiment.md`](docs/experiment.md), [`docs/limits.md`](docs/limits.md).
