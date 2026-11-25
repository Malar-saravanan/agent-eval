# Design

## Architecture

```
Vue UI ──► NestJS API (SQLite) ──HTTP──► Python worker
                                          ├─ /trial                   run one trial, grade, return trace + metrics
                                          ├─ /v1/chat/completions     metering model gateway  ──► Azure OpenAI
                                          ├─ harness adapters         hermes, opencode
                                          └─ graders                  unit_tests | exact_match | fs_state | llm_judge
```

### Boundaries

The API owns state (configs, experiments, trials, queue, statistics, export). The worker is stateless: it accepts `{trial_id, task_id, config}` and returns a complete result. The contract between them is a single JSON schema.

### The metering gateway

Both harnesses speak the OpenAI chat protocol. The worker exposes one endpoint that:

- maps the logical model name to an Azure deployment, injecting `api-version` and `api-key`;
- strips parameters the deployment rejects (e.g. `reasoning_effort`);
- applies per-trial overrides (temperature);
- authenticates every request against a random per-trial bearer secret (not the trial id);
- enforces step and token budgets centrally — harness-level flags cannot drift between adapters;
- records tokens, latency, resolved model snapshot, and cost identically for every call.

The result is that cost and usage figures are comparable across harnesses and traceable per trial regardless of what each harness itself reports.

---

## Adapter model

**Harness.** `Harness.run(ctx) → Result(events, final_text, timed_out, exit_code, complete, stderr)`; `capabilities ⊆ {skills, memory}`. Adapters translate native output — Hermes `stream-json`, OpenCode `--format json` — into a common event stream: `assistant | tool_call(kind=tool|skill|memory) | tool_result | error`. Tasks that require a capability the harness lacks resolve to `not_applicable` and are excluded from statistics.

**Model.** An entry in `config/models.yaml` (deployment env var, input/output price per 1M tokens). No code change.

Both adapter interfaces are exercised by a regression test that registers a dummy third harness and runs it through the full trial lifecycle without touching core code.

---

## Data model (SQLite)

| Table        | Key fields |
|--------------|---|
| `configs`    | `id=name@vN`, content hash, harness, model, settings `{skills, memory, temperature, max_turns, token_budget, nudge}`. Immutable; any settings change produces a new version. |
| `experiments`| name, trials_per_task, config_ids, task_ids |
| `trials`     | experiment, config, task, trial_idx, status, score, reasoning, duration, cost, usage, trace events, final_text, files, provenance meta |

A unique index on `(experiment_id, config_id, task_id, trial_idx)` prevents duplicate trials. Every write to a `trials` row goes through a whitelisted status set; a malformed worker reply is converted to `infra_error` rather than left in `running`.

**Trial status:** `passed | failed | timeout | infra_error | grader_error | not_applicable`. Statistics use `passed`, `failed`, and `timeout` (the last scored zero). `infra_error` is retried up to three times with exponential backoff, then excluded. `grader_error` is excluded. Neither is ever silently scored zero.

---

## Isolation

### Per-trial

- Fresh workdir (copy of the task fixture) and fresh harness home under `/runs/<trial_id>/`, deleted after the trial. Hermes's state directories are copied from a warm template; its ~470 MB of path-bound dependencies are shared via symlink.
- **Memory on** runs a seed session against the same home, then the task against it. **Memory off** omits the seed. No state persists across trials.
- **Skills on** installs the task's skill files into the harness's skill directory, through a no-follow installer that refuses to write through a symlink.

### Sandbox

The agent runs arbitrary shell. Everything it can touch is treated as hostile.

- Each trial runs as its own unprivileged uid, allocated exclusively, with a scrubbed environment (`PATH, LANG, LC_ALL, TERM, TZ, HOME`). The Azure key is never in the agent's environment.
- Tasks are copied to `/srv/tasks` (mode 700, root) at worker boot; hidden tests and reference solutions are unreadable. `/runs` is mode 711; each trial directory is mode 700. Trials cannot list or read each other's files.
- Leftover processes are killed at trial end by uid (Hermes leaves ~300 MB of daemons behind per run).

### Access control

- **`/trial`** — starting a trial is a privileged operation (it spends budget and manages filesystem state). The endpoint requires a random secret published by the worker to a root-only file on a volume shared with the API. Agents share the worker's network namespace but cannot read that file.
- **Model gateway** — only the random per-trial bearer secret issued at trial start is accepted. An agent cannot call Azure unmetered, spend another trial's budget, or grow server state with invented tokens.
- Trial and task ids must match `[A-Za-z0-9_-]{1,64}` (they become path components). Validated at the HTTP boundary.

Verified live as an unprivileged user: `/trial` without or with a wrong token returns 401; `/v1/chat/completions` without or with a forged token returns 401; `/ipc/worker-token` and `/srv/tasks` are unreadable.

### Grading

The grader does not trust the workdir.

- All file reads go through a no-follow reader: symlinks, FIFOs, device files, and paths containing `..` are refused. A symlink to a reference solution or to `/proc/1/environ` cannot satisfy a check; a FIFO cannot stall the worker.
- Hidden pytest tests execute from a root-owned directory outside the workdir, with `python -P` (no cwd on `sys.path`), no ini or conftest discovery, and the agent's workdir appended to `sys.path` last. A planted `conftest.py`, `pytest.ini`, or `pytest/` package in the workdir cannot alter the outcome.
- A pass requires both exit code 0 **and** pytest's `N passed` summary with `N ≥ number of hidden tests`. Exit code alone is forgeable through session hooks or `os._exit`.
- Graders run on a thread pool; one slow grader does not stall the gateway.
- The LLM judge delimits the agent's output as untrusted and rejects verdicts whose shape (criterion ids, boolean types) does not match the rubric.

An integrity audit of the first full 300-trial run found 0 of 1,124 agent tool calls touching hidden tests, solutions, the API key, or other trials. An independent review subsequently identified the holes above (reachable `/trial`, unauthenticated gateway, grader hijack, blocking reads); each is now closed and pinned by a regression test. Residual risk is enumerated in `limits.md`.

---

## Budgets

`max_turns` (steps = model calls that offer tools) and `token_budget` (prompt + completion tokens) are checked in the gateway on every request. When exhausted, the gateway returns `400 budget_exhausted`; the trial is graded on its final state and the trace carries a `budget_exhausted` error event. The same limits apply to Hermes and OpenCode without relying on harness-specific flags (OpenCode has no step-limit flag of its own).

The window is reset between the memory-seed phase and the task phase so that memory-on configurations never receive a smaller effective budget than memory-off.

---

## Reproducibility

Configs are content-hashed and immutable (`name@vN`). Every trial additionally persists a `meta` block:

- harness version string
- Azure deployment name as configured
- the model snapshot id Azure actually served (e.g. `gpt-4.1-mini-2025-04-14`)
- content hash of the task directory (fixture + tests + skills)
- the step and token budgets applied
- the nudge flag
- the trial's sandbox uid

The statistical bootstrap is seeded. LLM sampling is not reproducible — hence N repeated trials — but the inputs of every trial and the analysis of its outputs are.

### Crash safety and honest classification

Trials live in SQLite; on API restart, queued and running rows are re-queued. A platform failure is never recorded as an agent failure:

- a harness that produced no output, was killed, exited without its completion marker, or lost its connection → `infra_error`
- a would-be `failed` or `timeout` trial accompanied by any gateway error (429, 5xx, hang, dropped stream) → `infra_error`
- a grader fault or malformed task definition → `grader_error`

Both statuses are excluded from statistics. `infra_error` is retried; a passing trial is never downgraded because throttling occurred alongside it. Budget exhaustion is the agent's outcome and is graded.

The worker streams whitespace heartbeats while a long trial runs so Node's 300 s header timeout cannot trigger a duplicate retry, and refuses a second concurrent request for the same trial id.

---

## Graders

| Type          | Method |
|---------------|--------|
| `unit_tests`  | hidden pytest files copied in post-run; pass iff exit 0 and summary matches |
| `exact_match` | normalised comparison to `expected`; answer read from a file or an `ANSWER:` line (case-insensitive, tolerates Markdown and trailing period) |
| `fs_state`    | assertions on the final file system — exists, contains, YAML equals, SHA unchanged (strict type equality: `True != 1`) |
| `llm_judge`   | rubric of binary criteria, JSON output at temperature 0, score = fraction satisfied, one retry on unparseable output |

Judge validation: 30 human-labelled samples (10 per judge task), per-criterion agreement and Cohen's kappa. See `judge-validation.md`.

---

## Statistics

The unit of analysis is the **task**; trials within a task are repeated measures.

For configurations A and B:

1. Compute per-task mean score for each configuration over its scored trials; keep only tasks present in both.
2. Compute the 95% CI on the mean paired difference via a hierarchical bootstrap: 2000 resamples over tasks, then over trials within each resampled task; seeded.
3. **Verdict:**
   - `b_better` / `a_better` when the CI excludes zero (beyond an ε of 1e-9 to suppress floating-point ambiguity).
   - `inconclusive` when the CI spans zero with ≥ 3 paired tasks.
   - `insufficient_data` when fewer than 3 paired tasks are available or the CI is non-finite.
4. Secondary: McNemar's exact test on per-task pass/fail (a task passes if its mean score is ≥ 0.5).
5. Per-task deltas with their own bootstrap CIs; a per-task flag of "significant" additionally requires ≥ 2 trials on each side.
6. Cost, latency, and tokens use the same machinery.

### Choice of N

N = 5 was chosen a priori from cost (~$0.015/trial) and the observation that most tasks are near-deterministic; no formal pilot was run. The main experiment provides the retrospective evidence: within-task standard deviation averaged 0.03–0.06, so most variance lies **between** tasks. Achieved precision with 20 tasks: 95% CI half-width ≈ 0.10 on a paired Hermes-vs-Hermes difference and ≈ 0.15–0.20 on the 18-task cross-harness difference (replicated). Aggregate effects below ~0.10–0.15 cannot be resolved by this suite; additional trials would not materially change that. Broader or harder tasks would.

### Failure classification

Failed trials are labelled by rules on the trace, first-match-wins:

```
timeout → grader_error → budget_exhausted → capability_disabled
       → hallucinated_tool_args → capability_unused → gave_up_early
       → judge_borderline → wrong_answer
```

These are heuristics — useful for pointing a regression at a cause, not ground truth. The UI prints the definition of each category alongside the counts.

---

## Assumptions

1. The Azure endpoint accepts `chat/completions` with `api-key` and `api-version` headers, and the deployment supports tool-calling.
2. Token prices (gpt-4.1-mini: $0.40 in / $1.60 out per 1M) come from public trackers. Cached-input discounts are not modelled; reported cost is an upper bound.
3. Timeouts count as failures with score 0; infrastructure errors do not.
4. OpenCode has no native step limit, so the gateway enforces `max_turns` for every harness uniformly. Hermes also enforces `--max-turns` locally.
5. OpenCode has no persistent memory: memory-only tasks resolve to `not_applicable` for it.
6. Both harnesses run with auto-approval (`--yolo` / permission allow). The sandbox boundary is an unprivileged per-trial uid inside one worker container, not a container or VM per trial.
7. Skills and memory availability are controlled by the platform (installed files, seed session), not by harness flags. "Skills on" means *installed and discoverable*, not *used*.
8. The `nudge` setting appends one sentence to the task prompt directing the agent to check its skills and memory first. It is part of the configuration (prompting strategy is part of a harness) and serves as a positive control.
