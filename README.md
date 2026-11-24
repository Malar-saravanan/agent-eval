# Agent Evals Platform

Evaluate **any harness (X) with any model (Y)** over a task set, N trials each, and answer
*"did it get better, worse, or stay the same, and how sure are we?"* with paired statistics and full trajectories.

Harnesses: **Hermes Agent**, **OpenCode**. Models: Azure OpenAI deployments (`gpt-4.1-mini` now; more = one YAML entry).

## Run

```bash
cp .env.example .env      # fill AZURE_OPENAI_API_KEY, endpoint, deployment names
docker compose up --build
# UI + API: http://localhost:3000   (set API_PORT in .env if 3000 is taken)
```

Requirements: Docker with **>= 6 GB memory** (each running trial uses ~300-400 MB; lower `CONCURRENCY` in `.env` on small machines) and an Azure OpenAI chat deployment that supports tool calling.
First boot builds the worker image (installs Hermes + OpenCode, ~3 min) and a one-time warm-up (~1 min) before the first trial starts; later boots take seconds.

### Use

**Configs** tab -> create configs -> **Experiments** -> pick configs, tasks, N -> Start -> open the experiment for the summary, the **Compare** panel (A vs B), the failure analysis and per-trial trajectories. Export JSON/CSV from the experiment page.

### Reproduce the reported experiment (`docs/experiment.md`)

Create these four configs (harness / model `gpt-4.1-mini` / settings), then start an experiment with the first three, all tasks, N=5 (~25 min, ~$4.5):

| name | harness | skills | memory | nudge |
|---|---|---|---|---|
| `hermes-plain` | hermes | off | off | off |
| `hermes-full` | hermes | on | on | off |
| `opencode-skills` | opencode | on | (n/a) | off |
| `hermes-nudge` (control, with `hermes-full`, tasks 02, 11, 14, 17-20) | hermes | on | on | on |

Settings default to temperature 0.2, 30 steps, 300k tokens per trial. A **step** is one model call that offers tools; budgets are enforced in the gateway for every harness.

## Layout

```
api/      NestJS: configs, experiments, trial queue, stats, export (SQLite via node:sqlite). Serves the built UI.
web/      Vue 3 + TS UI (Vite)
worker/   Python/FastAPI: model gateway (metering), harness adapters, graders, trial runner
tasks/    task definitions (task.yaml + fixture/ + hidden tests/ + skills/)
config/   models.yaml (model registry + prices)
docs/     design.md, experiment.md, cost.md, limits.md, judge-validation.md, api.md, submission-checklist.md, demo-script.md
```

## Add a task

Create `tasks/<id>/task.yaml` (see any existing task):

```yaml
id: 21-my-task
title: ...
category: code            # code | fs | exact | judge | skill | memory
prompt: |                 # what the agent is told
  ...
requires: []              # [skills] and/or [memory] -> harnesses lacking it get "not_applicable"
setup: {skills: [name], memory_seed: "prior-session message"}   # optional
grader:                   # one of:
  type: unit_tests        #   hidden tests in tasks/<id>/tests/ are copied in AFTER the run
  # type: exact_match     #   expected: "42", source: final_answer | file:answer.txt
  # type: fs_state        #   checks: [{file_exists: x}, {file_contains: [f, text]}, {yaml_eq: [f, {...}]}, ...]
  # type: llm_judge       #   rubric: [criteria], files: [output files shown to the judge]
limits: {timeout_s: 240, max_turns: 20}
```
Put starting files in `tasks/<id>/fixture/`. The worker copies `tasks/` into a root-only directory at boot (so agents cannot read hidden tests), so after adding or editing a task run `docker compose restart worker`. Run `python tasks/validate.py` to check the untouched fixture fails and the reference `solution/` passes.

## Add a model

Add an entry to `config/models.yaml` (name, `deployment_env`, prices) and the deployment env var to `.env`. Nothing else changes: harnesses reach every model through the worker's OpenAI-compatible gateway (`/v1/chat/completions`), which maps the model name to the Azure deployment, adds `api-version`/`api-key`, and records tokens + latency per trial.

## Add a harness

In `worker/harnesses.py` subclass `Harness`: set `name` and `capabilities` (`skills`, `memory`), implement `run(ctx) -> Result` by invoking the CLI against `GATEWAY_URL` with `ctx.trial_id` as the API key, and translate its output into the common trace events (`assistant`, `tool_call`, `tool_result`, `error`). Register it in `HARNESSES` and add it to `HARNESSES` in `api/src/catalog.ts`. Core code (queue, graders, stats, UI) is untouched. `Hermes` and `OpenCode` are ~50 lines each.

## Tests

```bash
cd api && npm ci && npm test                         # 55 tests: stats (bootstrap CI, McNemar), failure classifier, config versioning + input validation, queue retries, export safety
cd worker && pip install -r requirements.txt && MODELS_FILE=../config/models.yaml python -m pytest tests -q
                                                     # 151 tests (4 need Linux /proc and are skipped on macOS; all run inside the container):
                                                     # graders incl. anti-tamper, gateway auth/budgets/errors, trial classification, sandbox/reaping, adapters
python tasks/validate.py                             # needs: pip install pytest pyyaml httpx fastapi; every task fails untouched and passes with its reference solution
```

Tests are offline: no Azure calls, no Hermes/OpenCode binaries. Inside the running stack: `docker compose exec worker python -m pytest tests -q` (set `MODELS_FILE=/config/models.yaml`).

## Design in one paragraph

A NestJS control plane stores configs/experiments/trials in SQLite and schedules trials; a Python worker runs each trial as its own unprivileged user in a fresh directory, with Hermes or OpenCode talking to Azure only through a metering gateway that enforces budgets and records tokens/latency; graders score the result; the API computes paired bootstrap statistics and groups failures by cause. Infrastructure failures are retried and never scored. See `docs/design.md`.

## Assumptions

See [docs/design.md](docs/design.md) (assumptions) and [docs/limits.md](docs/limits.md).
