# Known limits

Where not to trust these conclusions.

## Statistical power

- **Task count (20).** The statistical unit is the task. CI width on an aggregate difference is driven by 20 tasks, not by trials. Aggregate effects below ~0.10–0.15 are not detectable. "Within noise" means *not detected*, not *no difference*.
- **Ceiling and floor effects.** 11 of 20 tasks score 1.00 on every configuration; two more (17, 20) score 0.00 on every configuration. The suite discriminates on roughly 7 tasks. "Within noise" at the aggregate is partly a consequence of this.
- **No multiplicity correction on per-task flags.** With 20 per-task intervals at 95%, approximately one spurious "significant" flag is expected per comparison. Replication confirms this (see `experiment.md` → Replication). Per-task flags are leads for trace inspection, not findings.

## Task design

- **Author-written suite, single author.** Difficulty, rubric wording, and the skill/memory task design reflect one person's choices. No claim about general agent ability follows.
- **Discriminating tasks are built to be sensitive.** Tasks 17–20 are constructed so that skills or memory are *necessary*. Effects observed there are upper bounds on what a configuration's handling of those features is worth.
- **Contamination.** Tasks 01–07 are classic exercises (LRU cache, Roman numerals, pagination); near-identical problems appear in training data. Those scores measure recall of standard solutions as much as agentic ability.
- **Task 19 was reworded after an observed failure** ("standard port" → "our project's port"). This is a form of tuning on the evaluation; see `experiment.md`. It affects only task 19.

## Single model

- Every result is from one Azure deployment (`gpt-4.1-mini`). Harness differences are confounded with how that model suits each harness's prompting and tool schema; another model could reverse the ranking.
- **The brief asks for two models or one open-weight model.** Adding a model is a single YAML entry plus an env var; no run has been performed with a second model.
- **Non-determinism and API drift.** Temperature is fixed at 0.2 but the deployment is not seeded; Azure snapshots can roll. Results are reproducible in distribution, not per trial.
- **Feature use ≠ feature value on this model.** Skills had no measurable effect because the model did not open them unprompted. A nudge halved `capability_unused` failures without changing scores, suggesting the skill tasks may simply be hard for this model. One model cannot separate "too hard a task" from "a weak skill mechanism".

## Judge

- The judge is in the same model family as the subject (`gpt-4.1-mini`). Self-preference risk is not neutralised.
- Pooled agreement with human labels is 79%, Cohen's kappa 0.55 (see `judge-validation.md`). Agreement is weak on counting (task 14 bullet count) and whitespace (task 15 blank line, kappa 0.00). Deterministic graders carry the headline numbers; judge scores should be treated as noisier.
- Human labels were produced by the same party that wrote the rubrics and tasks. Agreement overstates independent validity.
- Prompt-injection into the judge is mitigated by delimiting the agent's output as untrusted, but not eliminated.
- Judge token usage is metered but not attributed to the trial it graded. Per-trial cost excludes grading cost (~$0.001 per judged trial).

## Harness comparison

- Comparing harnesses on the same model bundles many differences (system prompt, tool set, skill discovery, file-write semantics, token overhead). The comparison identifies **that** the bundles differ on specific tasks; it does not isolate **which** component is responsible.
- "Skills off" is not "no skills" — the Hermes template ships bundled default skills in every configuration; "off" means the task's own skill is not installed. Likewise "memory off" means no seed session, not that the memory tool is disabled.
- Token-cost differences between harnesses are largely prompt overhead (~8–16k tokens of system prompt and tools per call), not "efficiency".
- OpenCode has no persistent memory: tasks 19–20 resolve to `not_applicable` and its aggregate is over 18 tasks (Hermes covers 20). The paired test handles this correctly; cross-harness aggregates should always be read as "shared tasks only".

## Sandbox

- Agents run as unprivileged per-trial users with a scrubbed environment. They cannot read hidden tests, solutions, the API key, or the `/trial` secret; cannot use the gateway without their own per-trial secret; cannot cause a planted `conftest.py` or `pytest.ini` to make failing tests pass.
- They share one kernel and one network namespace with the worker.
- Hermes requires a world-writable shared runtime directory (`installs/`); a hostile agent could tamper with it and affect later trials.
- Solution code runs inside the pytest process. A deliberately malicious solution could print a fake pytest summary. Mitigation is forthcoming (parse `junit-xml` or a plugin signal).
- Appropriate for cooperative models on this suite. Untrusted agents warrant per-trial containers or VMs.

## Measurement

- Prices are public-tracker list rates. Cached-input discounts are not modelled. Reported cost is an upper bound.
- Infra-aware reclassification is conservative: a trial that would have been `failed` or `timeout` is reclassified `infra_error` if any gateway error occurred. This can discard an agent failure that happened to coincide with throttling; it also means retries slightly favour trials with upstream trouble. With 0 gateway errors in the final runs, this had no effect on the reported results.
- If a memory seed fails to persist after 3 attempts, the trial is still graded. Memory-on numbers therefore include the agent's reliability at saving its own memory.
