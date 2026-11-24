# Experiment: do skills + memory help Hermes? (plus a Hermes vs OpenCode comparison)

Main experiment `e_6a98d06c` (300 trials), nudge control `e_e3a652f2` (70 trials). Export: `GET /api/experiments/<id>/export.json|csv`. Model: Azure `gpt-4.1-mini` for every config, temperature 0.2. **370 trials, 0 infra errors, 0 grader errors, 0 timeouts**, spend $5.95 ($4.36 + $1.59). Both ran on the final, reviewed code.

## Hypothesis (stated before the first run)

**H1 (primary, single axis):** same harness (Hermes), same model. Turning **skills + memory ON** improves the four tasks that need them (17-20) and is neutral on the other 16.
A = `hermes-plain@v1` (skills off, memory off), B = `hermes-full@v1` (skills on, memory on). Strictly two features change together; they are not separable here.

**H2 (exploratory, many axes differ):** Hermes vs OpenCode, same model. Different prompts, tools and skill mechanisms: a difference means "the harness bundles differ", not "component X".

## Setup

20 tasks x N=5 x 3 configs = 300 trials (10 are N/A: OpenCode has no memory, tasks 19-20). Concurrency 4. Each trial: fresh workdir and harness home, its own unprivileged uid, scrubbed environment, gateway budget 30 steps / 300k tokens. Stats: paired hierarchical bootstrap on task means (2000 resamples, seeded) plus McNemar on per-task pass/fail (`design.md`).

## Results

| config | scored | mean score (95% CI) | cost / trial | latency | tokens / trial |
|---|---|---|---|---|---|
| hermes-plain | 100 | 0.765 [0.585, 0.922] | $0.0143 | 17.7 s | 33.9k |
| hermes-full | 100 | 0.770 [0.588, 0.930] | $0.0147 | 17.3 s | 35.7k |
| opencode-skills | 90 | 0.822 [0.667, 0.956] | $0.0162 | 15.4 s | 38.9k |

**H1, plain -> full (20 paired tasks): diff +0.005, CI [-0.092, +0.108] -> within noise** (McNemar a-only 1, b-only 1, p = 1); cost +$0.0003 (CI spans 0). Overall, skills + memory did not change the score within the achievable precision (about +-0.10).

Per task (only these moved):

| task | plain | full | reading |
|---|---|---|---|
| **19-memory-server-conf** | 0.00 | **0.80** (CI [+0.40, +1.00]) | real effect, mechanism visible in the trace (below) |
| 11-count-errors | 0.60 | 0.00 (flagged SIG) | **spurious**: counting log lines depends on neither skills nor memory; see "Stability" |
| 14-summarize-readme | 0.70 | 0.60 | judge-scored, noise |
| 17-changelog, 18-lint (skills), 20-memory-util | 0.00 | 0.00 | the model never opened the skills (0 of 10 trials); task 20 has no cue that a convention exists |

**H2, hermes-full -> opencode-skills (18 paired tasks, memory tasks excluded): diff +0.011, CI [-0.178, +0.211] -> within noise** (a-only 1, b-only 2, p = 1). Opposing per-task effects cancel:

| task | hermes-full | opencode | what the traces show |
|---|---|---|---|
| 06-csv-group-sum | 1.00 | **0.00** (SIG) | OpenCode overwrote the provided `sales.csv` with invented data without reading it (5/5) |
| 11-count-errors | 0.00 | **1.00** (SIG) | Hermes counted with `grep '...(10\|11):..' \| wc -l` (also counts 11:01-11:59, answers 8 not 6); OpenCode read the log and bounded timestamps exactly |
| 18-lint-rules-skill | 0.00 | **0.80** (SIG) | **OpenCode opened the skill in 5 of 5 trials and passed 4 of 5; every pass used the skill.** Hermes opened it in 0 of 5 and passed 0 |

Skill use is the whole story on task 18: same model, same skill files, opposite behaviour. The harness's tool set and prompt decide whether the skill is discovered. On task 17 neither harness ever opened its skill (0 of 10 trials) and none passed.

## Stability: two independent replicates of the same experiment

The experiment was run twice on materially different builds of the platform (R1 before the independent code review, R2 final; R1 numbers are those recorded at the time, its raw rows were cleared when R2 started). Same configs, tasks and N.

| quantity | R1 | R2 (above) | stable? |
|---|---|---|---|
| mean score plain / full / opencode | 0.748 / 0.785 / 0.817 | 0.765 / 0.770 / 0.822 | yes (+-0.03) |
| H1 diff (full - plain) | +0.037 [-0.050, +0.150] | +0.005 [-0.092, +0.108] | yes: within noise both times |
| H2 diff (opencode - full) | 0.000 [-0.164, +0.147] | +0.011 [-0.178, +0.211] | yes: within noise both times |
| task 19 plain -> full | 0.00 -> 1.00 | 0.00 -> 0.80 | **yes, large and replicated** |
| task 06 OpenCode | 0.00 | 0.00 | yes |
| task 11 OpenCode vs Hermes | 1.00 vs 0.20 | 1.00 vs 0.00 | yes |
| task 18 OpenCode vs Hermes | 0.20 vs 0.00 | 0.80 vs 0.00 | direction yes, size no (4x) |
| task 11 plain vs full | 0.40 vs 0.20 (n.s.) | 0.60 vs 0.00 (SIG) | **no: noise** |
| task 14 plain vs full | 0.75 vs 0.50 (SIG) | 0.70 vs 0.60 (n.s.) | **no: judge noise** |

Lessons that drive how to read this platform: (1) aggregate scores and verdicts replicate; (2) large mechanistic per-task effects replicate (19, 06, 11 Hermes-vs-OpenCode, skill use on 18); (3) **single-task "significant" flags between configs that differ in nothing relevant do not replicate** (11 and 14 plain-vs-full), exactly what 20 uncorrected per-task intervals at 95% plus N=5 predict. So per-task flags are leads to inspect in the trace, not findings, and the aggregate CI is the verdict.

## Positive control: nudge (`hermes-nudge` = `hermes-full` + one sentence telling the agent to check its skills and memory first), 7 tasks x 5 trials

score 0.457 -> 0.629, diff +0.171, CI [+0.000, +0.393] -> inconclusive at the boundary; cost +$0.012/trial (CI excludes 0), +29.6k tokens, +5.3 s. `capability_unused` failures fall from 10 to 3: the nudge changes behaviour. Task 17 rose 0.00 -> 0.60 (flagged) in this run. I ran this control four times on slightly different builds during development; the diff was +0.079, +0.150, +0.029 and +0.171: always positive, never clearly excluding 0, and task 17 stayed 0.00 in three of the four runs: **suggestive, not established** with 7 tasks. The control still earns its keep: it shows the platform detects behaviour change (skill use) and prices it, and that effects on skill tasks are real but unstable for this model.

## Inspected trajectories

1. **Task 19, hermes-full (passes 4 of 5; plain 0 of 5).** Seed session: `memory(add "API port is 8081. Indentation style is tabs.")` saved to USER.md. Task session: trace starts with `memory_context -> USER.md: API port is 8081...`; the agent writes `listen 8081;` with tabs. hermes-plain never sees the fact and searches for a config that does not exist.
2. **Task 18, OpenCode vs Hermes (4/5 vs 0/5).** OpenCode globs and reads `.opencode/skills/lint-rules/`, then edits to satisfy the three project rules. Hermes reads `app.py`, applies generic cleanups, never opens its skill.
3. **Task 06, OpenCode (0/5).** `write agg.py`, then `write sales.csv` with invented rows over the provided file, runs on its own data, declares success. Hermes (5/5) did not do this: a harness-level read-before-write difference, not a model limit.

## Methodological notes and disclosures

- **Task 19's prompt was reworded after I saw it fail.** Original: "use the *standard* port and indentation"; with memory visible the model still wrote port 80. Now: "our project's port and indentation conventions" (no fact revealed). That is tuning on the evaluation; it affects only task 19, and the 0 -> 0.80 depends on that cue. Task 20 deliberately has no such cue and stays at 0 for every config.
- **Platform bugs found and fixed by checking surprising numbers (earlier runs discarded):** leaked Hermes daemons exhausting memory (fake "OpenCode 0.36 vs Hermes 0.83"); pytest's `tmp_path` crashing under per-trial users (task 06 showed 0.00 for Hermes); then an independent code review found a grader-hijack, an open `/trial`, an unauthenticated gateway and failure misclassification. All fixed with regression tests; the results above are from the fixed code. About $16 of runs were discarded along the way (`cost.md`).
- **Integrity audit** (earlier full run): 0 of 1,124 agent tool calls touched hidden tests, solutions, the key or other trials.

## What I would conclude, and not

- Supported: memory helps Hermes a lot when the task makes the remembered fact relevant (19, replicated); whether a harness opens a skill is decisive on a skill task (18) and differs strongly between harnesses; Hermes and OpenCode are equivalent overall on this suite but differ on specific tasks for explainable reasons; the nudge changes behaviour at a measurable cost.
- Not supported: anything about other models, about skills in general (two tasks, one skill each), or about which harness is "better".
- 11 of 20 tasks score 1.00 on every config and 2 more (17, 20) are 0.00 on every config, so the suite discriminates on only ~7 tasks; a harder, broader task set and a second model are the obvious next steps.
