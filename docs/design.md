# Design

## Architecture

```
Vue UI ──► NestJS API (SQLite) ──HTTP──► Python worker
                                          ├─ /trial   : run one trial (isolated), grade, return trace+metrics
                                          ├─ /v1/chat/completions : metering model gateway  ──► Azure OpenAI
                                          ├─ harness adapters (hermes, opencode)
                                          └─ graders (unit_tests, exact_match, fs_state, llm_judge)
```

**Boundary.** The API owns everything stateful (configs, experiments, trials, queue, stats, export). The worker is stateless: it receives `{trial_id, task_id, config}` and returns a complete result. The only contract is that JSON (see `docs/api.md` for the UI side).

**Why a gateway.** Both harnesses speak OpenAI-style chat. The worker exposes one endpoint that maps `model` -> Azure deployment, injects `api-version`/`api-key` (the Azure front door needs them; OpenCode drops `api-version` on custom Azure URLs), strips params Azure rejects (`reasoning_effort`), applies per-trial overrides (temperature), and records tokens/latency keyed by the trial id (used as the harness's API key). Token/cost/latency numbers are therefore captured identically for every harness, independent of what each harness reports.

## Adapter interfaces

- `Harness.run(ctx) -> Result(events, final_text, timed_out, exit_code)`; `capabilities ⊆ {skills, memory}`. Adapters translate native output (Hermes `stream-json`, OpenCode `--format json`) into the common event shape: `assistant | tool_call(kind=tool|skill|memory) | tool_result | error`. Tasks that `require` a capability the harness lacks are `not_applicable` (excluded, not failed).
- Models: an entry in `config/models.yaml` (deployment env var + prices). No code.

## Data model (SQLite)

| Table | Key fields |
|---|---|
| configs | `id=name@vN`, `hash`, harness, model, settings{skills,memory,temperature,max_turns}. Immutable; changing settings creates a new version. |
| experiments | name, trials_per_task, config_ids, task_ids |
| trials | experiment, config, task, trial_idx, status, score, reasoning, duration, cost, usage{tokens,calls,latency}, `events` (full trace), final_text, files |

Trial `status`: `passed | failed | timeout | infra_error | grader_error | not_applicable`. Stats use passed/failed/timeout (timeout = score 0, an agent outcome). `infra_error` (429s, upstream/worker failures) is retried up to 3 times with backoff and then excluded; `grader_error` (judge unparseable) is excluded. Neither is ever silently scored 0.

## Isolation and reproducibility

**Per-trial isolation**
- Fresh workdir (copy of the task fixture) and a fresh harness home under `/runs/<trial_id>/`, deleted after the trial. Hermes' state dirs are copied from a warm template; its 470MB dependency dirs are shared (symlinked), because Hermes' venv is path-bound and cannot be copied.
- Memory: **memory ON** means a seed session ("remember X") runs first in the same home, then the task runs; **memory OFF** skips the seed. Nothing persists across trials. Skills: **ON** installs the task's skill files into the harness' skill dir.

**Agent sandbox (the agent runs arbitrary shell, so everything it can touch is treated as hostile)**
- Each trial runs as its own unprivileged uid (allocated exclusively, never shared by concurrent trials) with a scrubbed environment (`PATH, LANG, TERM, TZ, HOME` only): the Azure key is not in the agent's environment.
- Tasks are copied at worker boot to `/srv/tasks` (mode 700, root): hidden tests and reference solutions are unreadable. `/runs` is mode 711 and each trial dir is 700, so a trial can neither list nor read another trial's files. The run dir is deleted after the trial and the user's leftover processes are killed (Hermes leaves ~300MB daemons behind).
- **Worker access control.** Agents share the worker container's network namespace, so `/trial` (which starts paid runs and wipes directories) needs a secret that only the API can read: the worker writes it to a root-only file on a volume shared with the API. The model gateway only accepts a random per-trial bearer secret issued at trial start (not the guessable trial id): an agent cannot call Azure unmetered, spend another trial's budget, or grow server state with invented tokens. Verified live: as an unprivileged user, `/trial` without or with a wrong token, `/v1/chat/completions` without or with a forged token all return 401, and `/ipc/worker-token` and `/srv/tasks` are unreadable. Trial and task ids must match `[A-Za-z0-9_-]{1,64}` (they become path components).
- **The grader does not trust the workdir.** Files are read only through a no-follow reader (symlinks, FIFOs, device files and `..` are refused: a symlink to a reference solution or `/proc/1/environ` must not satisfy a check, and a FIFO must not hang the worker). Hidden pytest tests run from a root-owned directory *outside* the workdir with no ini/conftest discovery, `python -P` (no cwd on `sys.path`) and the agent's directory appended to `sys.path` last, so a planted `conftest.py`, `pytest.ini` or `pytest/` package cannot change the outcome; a pass additionally requires pytest's own "N passed" summary with N >= the number of hidden tests (exit code 0 alone is forgeable). Graders run in a thread, so one slow grade cannot stall the gateway. The LLM judge delimits the agent's output as untrusted data and rejects non-boolean or mis-numbered verdicts.
- Audit of the first full run: 0 of 1,124 agent tool calls touched hidden tests, solutions, the key or other trials; an independent review then found the holes above (planted conftest, reachable `/trial`, unauthenticated gateway, blocking grader), each now closed and covered by a regression test.
- Residual risk (see `limits.md`): same kernel and network, no per-trial container; Hermes needs a world-writable shared runtime dir; solution code runs inside the pytest process, so a deliberately malicious solution could fabricate a pytest summary.

**Budgets are enforced in the gateway, not in each harness.** `max_turns` (steps = model calls that offer tools) and `token_budget` (prompt + completion tokens) are checked per request; once exhausted the gateway answers `400 budget_exhausted`, the trial still gets graded on its final state and the trace gets a `budget_exhausted` error event. This limits Hermes and OpenCode identically (OpenCode has no step-limit flag).

**Reproducibility record.** Configs are content-hashed and immutable (`name@vN`). Every trial additionally stores `meta`: harness version string, Azure deployment name, the model snapshot id Azure actually served (e.g. `gpt-4.1-mini-2025-04-14`), a hash of the task directory (fixture + tests + skills), the budgets applied and the nudge flag. The stats bootstrap is seeded. LLM sampling is not reproducible, which is why N repeated trials exist; what is reproducible is the *inputs* of every trial and the analysis of its outputs.

**Crash safety and honest classification.** Trials live in SQLite; on API restart queued/running trials are re-queued. A platform failure is never recorded as an agent failure: a harness that produced no output, was killed, died without its completion marker, lost its connection, or never reached the gateway is `infra_error`; so is any trial that would otherwise be `failed` or `timeout` while the model gateway returned errors (429/5xx/hangs/dropped streams); a grader or task-definition problem is `grader_error`. Both are excluded from statistics; `infra_error` is retried (3 attempts, backoff). A passing trial stays passed despite throttling. Budget exhaustion is the agent's outcome and is graded. The worker streams whitespace heartbeats while a trial runs so Node's 300s header timeout can never trigger a duplicate retry of a long trial, and refuses a second concurrent request for the same trial id.

## Graders

| Type | Method |
|---|---|
| unit_tests | hidden pytest files copied in post-run; pass = all green |
| exact_match | normalized compare to `expected`; answer read from a file or an `ANSWER:` line |
| fs_state | assertions on the final file system (exists / contains / yaml equals / file unchanged) |
| llm_judge | rubric of binary criteria, JSON output at temperature 0, score = fraction satisfied, retried once; unparseable -> `grader_error` |

**Judge validation:** 30 human-labelled samples (10 for each of the 3 judge tasks), per-criterion agreement and Cohen's kappa: see `docs/judge-validation.md`.

## Statistical method

Unit of analysis = **task** (trials within a task are repeated measures). For configs A and B:
1. Per-task mean score per config over its scored trials; only tasks present in both are paired.
2. 95% CI on the mean paired difference via a **hierarchical bootstrap** (2000 resamples of tasks, then trials within each sampled task; seeded).
3. Verdict: B better / A better only if the CI excludes 0 (and ≥3 paired tasks); otherwise **"within noise"**.
4. Secondary: McNemar exact test on per-task pass/fail (task passes if mean ≥ 0.5).
5. Per-task deltas with their own bootstrap CIs; cost/latency/tokens use the same machinery.

**Choosing N.** N=5 was chosen a priori from cost (~$0.015/trial) and the observation that most tasks are near-deterministic; **no pilot was run**. The main experiment gives the evidence after the fact: within-task SD of trial scores averaged 0.03-0.06, i.e. most variance is *between tasks*, which is why the unit of analysis is the task and extra trials mostly sharpen a few mixed-outcome tasks (06, 10, 11, 14, 18). Achieved precision with 20 tasks: 95% CI half-width ~0.10 on a paired Hermes-vs-Hermes difference and ~0.15-0.20 on the 18-task cross-harness difference (two replicates agree). So aggregate effects under ~0.10-0.15 cannot be resolved, and adding trials would not change that much; adding or diversifying *tasks* would. A cheap rule if cost matters: run N=2 first and top up only tasks whose trials disagree (see `cost.md`).

**Failure analysis.** Failed trials are classified by rules on the trace (first match wins): `timeout`, `grader_error`, `budget_exhausted`, `capability_disabled` (task needs skills/memory the config switched off: expected), `hallucinated_tool_args` (tool errors that name bad flags/arguments/schema), `capability_unused` (skills/memory were available but never invoked), `gave_up_early`, `judge_borderline` (partial judge score), `wrong_answer`. The experiment page tabulates categories per config so a regression points at a cause. These are heuristics, not ground truth: the legend states what each rule means.

## Assumptions

1. The Azure endpoint accepts chat-completions with `api-key` + `api-version`; function calling works on the deployment.
2. Token prices (gpt-4.1-mini: $0.40 in / $1.60 out per 1M) come from public trackers; cached-input discounts are not modelled, so cost is an upper bound.
3. Timeouts count as failures; infra errors do not.
4. OpenCode has no step-limit flag, so `max_turns` is enforced via the timeout only and a step overrun is logged as a trace error. Hermes enforces `--max-turns` natively.
5. OpenCode has no persistent memory: memory tasks are `not_applicable` for it.
6. Both harnesses run with auto-approval (`--yolo` / permission allow). The sandbox is an unprivileged per-trial uid inside the worker container, not a container or VM per trial.
7. Skill/memory availability is controlled by the platform (installed files, a seed session), not by Hermes/OpenCode flags, so "skills on" means "installed and discoverable", not "used".
8. The `nudge` setting appends one sentence to the task prompt telling the agent to check its skills and memory first. It is part of the config (prompting strategy is part of a harness) and is used as a positive control.
