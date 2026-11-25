# Experiment

Two paired comparisons on a 20-task suite, Azure `gpt-4.1-mini` as the single model, N = 5 trials per cell.

- Main (`e_6a98d06c`): 300 trials over three configurations.
- Nudge control (`e_e3a652f2`): 70 trials over two configurations on seven tasks.
- 370 trials total. 0 infrastructure errors, 0 grader errors, 0 timeouts. Spend: $5.95 ($4.36 + $1.59).

Both runs used the code in this repo. Raw exports are in [`docs/results/`](results/). Pull them with `GET /api/experiments/<id>/export.{json,csv}`.

---

## Hypotheses (pre-registered)

**H1 (primary, single axis).** Same harness, same model. Turning **skills + memory on** improves the four tasks that require them (17–20) and is neutral on the other 16.
A = `hermes-plain@v1` (skills off, memory off); B = `hermes-full@v1` (skills on, memory on).
Note: two features change together. They are not separable within this experiment.

**H2 (exploratory, multi-axis).** Hermes vs OpenCode on the same model. Different system prompts, tool schemas, and skill mechanisms — a difference indicates the **harness bundles** differ, not any one component.

---

## Setup

20 tasks × N=5 × 3 configurations = 300 trials. 10 trials are `not_applicable` (OpenCode has no memory; tasks 19 and 20).
The suite mixes code, files, exact match, and judge tasks, plus four that require skills or memory, so H1 is a settings comparison and H2 is a harness comparison on the same work — not a random prompt bag.
Concurrency 4. Each trial: fresh workdir, fresh harness home, exclusive unprivileged uid, scrubbed environment, 30 steps / 300k tokens enforced in the gateway.
Statistics: paired hierarchical bootstrap on task means (2000 resamples, seeded) plus McNemar's exact test on per-task pass/fail. See `design.md`.

---

## Headline

| config            | scored | mean score (95% CI)    | cost / trial | latency | tokens / trial |
|-------------------|--------|------------------------|--------------|---------|----------------|
| hermes-plain      | 100    | 0.765 [0.585, 0.922]   | $0.0143      | 17.7 s  | 33.9k          |
| hermes-full       | 100    | 0.770 [0.588, 0.930]   | $0.0147      | 17.3 s  | 35.7k          |
| opencode-skills   | 90     | 0.822 [0.667, 0.956]   | $0.0162      | 15.4 s  | 38.9k          |

---

## H1 — skills + memory

**plain → full, 20 paired tasks: Δ = +0.005, 95% CI [−0.092, +0.108] — within noise.**
McNemar: a-only 1, b-only 1, p = 1.00. Cost delta +$0.0003/trial (CI spans 0).

Aggregate effect is below the precision floor (~±0.10). Per task, only four move:

| task                        | plain | full | reading |
|-----------------------------|-------|------|---------|
| **19-memory-server-conf**   | 0.00  | **0.80** (CI [+0.40, +1.00]) | real effect; mechanism visible in the trace |
| 11-count-errors             | 0.60  | 0.00 (flagged significant)   | spurious — neither skills nor memory can affect log-counting; see Replication |
| 14-summarize-readme         | 0.70  | 0.60                         | judge-scored noise |
| 17-changelog, 18-lint, 20-util | 0.00 | 0.00                      | skills never opened (0 of 10 trials on 17 and 18); 20 carries no cue a convention exists |

**Finding.** Memory produces a decisive, mechanistically explained effect on the single task where the remembered fact is required (19). Skills produce no measurable effect on `gpt-4.1-mini` because the model does not consult them unprompted. The aggregate signal hides a +1.00 effect on one task and 0 on three — per-task deltas are therefore essential to any interpretation.

---

## H2 — Hermes vs OpenCode

**hermes-full → opencode-skills, 18 paired tasks (memory tasks excluded): Δ = +0.011, CI [−0.178, +0.211] — within noise.**
McNemar: a-only 1, b-only 2, p = 1.00. Opposing per-task effects cancel.

| task                     | hermes-full | opencode | trace evidence |
|--------------------------|-------------|----------|----------------|
| 06-csv-group-sum         | 1.00        | **0.00** (sig) | OpenCode overwrote the provided `sales.csv` with invented data without reading it (5 of 5) |
| 11-count-errors          | 0.00        | **1.00** (sig) | Hermes counted with `grep '...(10\|11):..' \| wc -l` (also matches 11:01–11:59; answer 8, expected 6); OpenCode read the log and bounded timestamps exactly |
| 18-lint-rules-skill      | 0.00        | **0.80** (sig) | **OpenCode opened the skill in 5 of 5 trials and passed 4 of 5; every pass used the skill.** Hermes opened it in 0 of 5 and passed 0 |

**Finding.** Same model, same skill files, opposite outcomes on 18. The harness's tool set and system prompt decide whether a skill is discovered. Neither harness ever opened its skill on task 17 (0 of 10); neither passed.

---

## Replication

The main experiment was executed twice on materially different builds (R1 before the independent review, R2 above). Same configs, tasks, and N.

| quantity                         | R1                        | R2 (final)                | stable?                    |
|----------------------------------|---------------------------|---------------------------|----------------------------|
| mean score plain / full / opencode | 0.748 / 0.785 / 0.817  | 0.765 / 0.770 / 0.822     | yes, within ±0.03          |
| H1 Δ (full − plain)              | +0.037 [−0.050, +0.150]   | +0.005 [−0.092, +0.108]   | yes — within noise both times |
| H2 Δ (opencode − full)           |  0.000 [−0.164, +0.147]   | +0.011 [−0.178, +0.211]   | yes — within noise both times |
| task 19 plain → full             | 0.00 → 1.00               | 0.00 → 0.80               | **yes, large and replicated** |
| task 06 OpenCode                 | 0.00                      | 0.00                      | yes                        |
| task 11 OpenCode vs Hermes       | 1.00 vs 0.20              | 1.00 vs 0.00              | yes                        |
| task 18 OpenCode vs Hermes       | 0.20 vs 0.00              | 0.80 vs 0.00              | direction yes, magnitude no |
| task 11 plain vs full            | 0.40 vs 0.20 (n.s.)       | 0.60 vs 0.00 (sig)        | **no — flag noise**        |
| task 14 plain vs full            | 0.75 vs 0.50 (sig)        | 0.70 vs 0.60 (n.s.)       | **no — judge noise**       |

**How to read this platform.** Aggregate verdicts replicate. Large mechanistic per-task effects replicate. Isolated "significant" per-task flags between configurations that differ in nothing causally relevant do not — exactly what 20 uncorrected intervals at 95% plus N = 5 predict. Treat per-task flags as leads to inspect in the trace; the aggregate CI is the verdict.

---

## Positive control — nudge

`hermes-nudge` = `hermes-full` with one sentence prepended to the prompt directing the agent to check its skills and memory first. Seven tasks × 5 trials.

- Score: 0.457 → 0.629. Δ = +0.171, CI [+0.000, +0.393]. Verdict at the boundary.
- Cost: +$0.012/trial (CI excludes 0). Tokens: +29.6k. Latency: +5.3 s.
- `capability_unused` failures fall from 10 to 3 — behaviour changes measurably.
- Task 17 rose 0.00 → 0.60 (flagged) in this run. Across four control runs during development the Δ was +0.079, +0.150, +0.029, +0.171: always positive, never clearly excluding 0; task 17 remained 0.00 in three of the four.

**Reading.** The control earns its keep: the platform detects behaviour change, prices it, and shows that skill-task outcomes are real but unstable for this model. The nudge effect is suggestive, not established at N = 5 across 7 tasks.

---

## Inspected trajectories

1. **Task 19, hermes-full (4 of 5 pass; plain 0 of 5).** Seed session writes `USER.md` via `memory(add "API port is 8081. Indentation style is tabs.")`. The task session's trace opens with `memory_context → USER.md: ...`, and the agent writes `listen 8081;` with tab indentation. `hermes-plain` never sees the fact and searches for a configuration file that does not exist.

2. **Task 18, OpenCode vs Hermes (4 of 5 vs 0 of 5).** OpenCode globs `.opencode/skills/lint-rules/`, reads the rule file, and edits to satisfy the three constraints. Hermes reads `app.py`, applies generic refactors, never opens its skill.

3. **Task 06, OpenCode (0 of 5).** OpenCode writes `agg.py`, then overwrites the provided `sales.csv` with invented rows, runs the script against its own data, and declares success. Hermes (5 of 5) does not do this — a harness-level read-before-write difference, not a model limitation.

---

## Methodological notes

- **Task 19 reworded after observing failure.** The original prompt — "use the *standard* port and indentation" — led the model to write port 80. The current prompt — "our project's port and indentation conventions" — reveals no fact. This is a form of tuning on the evaluation and affects task 19 alone. The 0 → 0.80 result is conditional on that cue. Task 20 deliberately carries no analogous cue and remains 0 for every configuration.
- **Platform bugs found by investigating surprising numbers (earlier runs discarded).** Leaked Hermes daemons exhausted worker memory and corrupted an early run (fabricated "OpenCode 0.36 vs Hermes 0.83"). `pytest.tmp_path` crashed under per-trial users and scored task 06 as 0.00 for Hermes. An independent review then found a grader-hijack via planted `conftest.py`, an unauthenticated `/trial`, an unauthenticated gateway, and failure misclassification. All fixed with regression tests. Approximately $16 of discarded compute is itemised in `cost.md`.
- **Integrity audit** of the first full run: 0 of 1,124 agent tool calls touched hidden tests, solutions, the API key, or other trials. The sandbox was subsequently tightened to make these structurally impossible.

---

## Conclusions

**Supported by this experiment:**
- Memory meaningfully improves Hermes when the task requires the remembered fact (task 19, replicated).
- Whether a harness discovers the task's skill is decisive on the skill task where the model engages (task 18); the two harnesses differ sharply here on the same model and skill files.
- Hermes and OpenCode are statistically indistinguishable in aggregate on this suite, with explainable opposing per-task behaviours.
- The nudge measurably changes agent behaviour at a measurable cost.

**Not supported:**
- Any claim about other models.
- Any claim about skills in general — two skill tasks, one skill each.
- Any ranking of Hermes vs OpenCode "overall".

**Headroom.** 11 of 20 tasks score 1.00 on every configuration; two more (17, 20) score 0.00 on every configuration. The suite discriminates on roughly 7 tasks. A broader and harder task set, and a second model, are the clear next steps.
