# Cost

## Formula

```
cost = tasks × trials × configs × avg_tokens_per_trial × blended_price_per_token
```

With `blended_price = (p_in × $0.40 + p_out × $1.60) / 1M` for `gpt-4.1-mini`. Agent trials are ~98% input tokens (the conversation grows every step and Hermes/OpenCode ship 8–16k tokens of system prompt and tool schema per call), so the effective blended rate is ~$0.42 per 1M tokens.

**Worked example.** 20 tasks × 5 trials × 3 configs = 300 trials (290 run, 10 `not_applicable`) × ~36k tokens ≈ 10.5M tokens × ~$0.42/1M ≈ **$4.40**. Actual: $4.36.

---

## Actual spend

Main experiment `e_6a98d06c` (300 trials) and nudge control `e_e3a652f2` (70 trials):

| configuration    | trials run | $/trial            | total   |
|------------------|------------|--------------------|---------|
| hermes-plain     | 100        | 0.0143             | $1.43   |
| hermes-full      | 100        | 0.0147             | $1.47   |
| opencode-skills  | 90         | 0.0162             | $1.46   |
| **main**         | **290**    |                    | **$4.36** |
| nudge control    | 70         | 0.0167 / 0.0287    | $1.59   |

Mean tokens per trial: 33.9k (plain), 35.7k (full), 38.9k (OpenCode). The nudge adds ~29.6k tokens per trial — the extra sentence makes the agent explore.

Judge calls — three judge tasks × ~15 trials ≈ 45 calls of ~1k tokens, plus a 30-sample validation run — are metered by the gateway but not attributed to individual trials. Total well under $0.10.

**Not included.** Approximately $25 of discarded runs during platform development: two corrupted by a Hermes daemon leak, one by a grader bug, plus several superseded smoke runs and an earlier replicate (R1) now reported only as a stability check. The cost of fixing infrastructure on smaller runs before scaling is real.

Prices are public-tracker list rates; cached-input discounts are not applied. Reported figures are upper bounds.

---

## Reducing cost

1. **Early stopping.** 11 of 20 tasks produce 5/5 for every configuration. A two-trial pilot per task followed by continuation only on mixed outcomes would cut trial count ~40% here without changing the verdict.
2. **Task sampling.** Drop tasks saturated at 1.00 or 0.00 across configurations; they carry no comparative signal. Keep a small canary set for regression.
3. **Prompt caching.** Azure offers a discount on cached input; Hermes already reports large cache reads. With ~98% of spend on input, accounting for this could cut real spend by a third or more.
4. **Trim harness overhead.** Restricting toolsets shrinks the per-call system prompt and improves cross-harness comparability.
5. **Cheaper judge, deterministic graders first.** 17 of 20 tasks use deterministic graders. Cache judge calls keyed on (rubric, response) for re-grading. Never cache agent trials — fresh samples are the point.
6. **Pilot small, then scale.** Run N = 2 to identify saturated tasks and estimate variance; scale only where it matters.
7. **Reuse across experiments.** Configs are immutable and content-hashed; a baseline configuration's trials can be reused when a new configuration is introduced.
