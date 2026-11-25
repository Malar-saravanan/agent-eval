# Agent Evals Platform

Compare agent setups (harness × model × settings) on the same tasks. You get scores with CIs, traces, cost, and retries when Azure or the worker dies — those trials are not scored as the agent failing.

Harnesses: **Hermes Agent**, **OpenCode**. Model: Azure OpenAI `gpt-4.1-mini`. Another harness or model is a small adapter, not a rewrite.

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
2. **Experiments** — pick configs, tasks, and trials-per-task, then start. The queue runs a few at a time and retries worker/Azure failures.
3. **Results** — mean scores and CIs, pairwise compare with a forest plot, cost/latency/tokens, failure buckets, and the trace for each trial. Export JSON or CSV.

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
api/      NestJS — configs, experiments, trial queue, stats, export (SQLite). Serves the built UI.
web/      Vue 3 + TypeScript UI (Vite).
worker/   Python / FastAPI — metering model gateway, harness adapters, graders, trial runner.
tasks/    Task definitions (task.yaml + fixture/ + hidden tests/ + skills/).
config/   Model registry and prices.
docs/     project-summary (1-page brief), design, experiment, cost, limits, judge-validation, api, results/ (raw JSON+CSV), screenshots/.
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

## How a run works

The API stores configs and trials in SQLite and calls the Python worker. Each trial is a throwaway Linux user in a fresh directory. Hermes and OpenCode only talk to Azure through a gateway that counts tokens and enforces step/token limits. After the run, a grader (hidden tests, files, exact match, or an LLM rubric) scores it. Compare uses a paired bootstrap. If the platform failed, that trial is retried and left out of the score.

More detail: [`docs/design.md`](docs/design.md), [`docs/experiment.md`](docs/experiment.md), [`docs/limits.md`](docs/limits.md).
