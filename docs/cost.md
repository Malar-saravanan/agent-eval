# Cost estimate

## Formula

```
cost = tasks x trials x configs x avg_tokens_per_trial x blended_price_per_token
```
with `blended_price = (input_share x $0.40 + output_share x $1.60) / 1M` for gpt-4.1-mini. Agent trials are ~98% input tokens (the prompt grows every step and Hermes/OpenCode send 8-16k tokens of system prompt + tools each call), so the effective blended price is ~$0.42 / 1M tokens.

Worked example for the experiment: 20 x 5 x 3 = 300 trials (290 run, 10 are N/A) x ~36k tokens ≈ 10.5M tokens x ~$0.42/1M ≈ **$4.4** (actual $4.36).

## Actual spend (final main experiment `e_6a98d06c`, 300 trials; nudge control `e_e3a652f2`, 70 trials)

| config | trials run | $/trial | total |
|---|---|---|---|
| hermes-plain | 100 | 0.0143 | $1.43 |
| hermes-full | 100 | 0.0147 | $1.47 |
| opencode-skills | 90 | 0.0162 | $1.46 |
| **main experiment** | 290 | | **$4.36** |
| nudge control (2 configs x 7 tasks x 5) | 70 | 0.0167 (full), 0.0287 (nudge) | $1.59 |

Mean tokens/trial: 33.9k (plain), 35.7k (full), 38.9k (OpenCode); the nudge costs +29.6k tokens/trial (it makes the agent explore). Judge calls (3 judge tasks x 15 trials ≈ 45 calls of ~1k tokens, plus a 30-sample validation run) are metered by the gateway but not attributed to trials: well under $0.10. Earlier discarded runs (two OOM/leak-corrupted, one with a grader bug, several superseded or smoke runs, and the previous replicate R1 that is reported only as a stability check) cost roughly another $25 and are not counted above; that is a real cost of building an eval platform: fix infra bugs on a small subset before launching full runs. Prices are public-tracker list prices ($0.40 / $1.60 per 1M); cached-input discounts are not modelled, so these are upper bounds.

## How to reduce cost

1. **Early stopping** - 11 of 20 tasks were 5/5 pass for every config. Run 2 trials first and only continue tasks where outcomes differ or are mixed: roughly -40% trials here, with no change to the verdict.
2. **Task sampling / difficulty filtering** - drop tasks saturated at 1.00 or 0.00 across configs (they carry no comparative information), keep a small canary set.
3. **Prompt caching** - Azure gives a discount on cached input and Hermes already reports large cache reads; with ~98% of spend on input, accounting for it could cut real spend by a third or more.
4. **Trim harness overhead** - limit toolsets (`--toolsets`) so the per-call system prompt is smaller; this is also a fairer harness comparison.
5. **Cheaper judge / deterministic graders first** - 17 of 20 tasks use deterministic graders; only judge tasks need a model. Cache judge calls keyed on (rubric, response) for re-grading (never cache agent trials: they need fresh samples).
6. **Pilot small, then scale** - N=2 pilot to find saturated tasks and estimate variance before the N=5 run.
7. **Reuse results across experiments** - configs are immutable and hashed, so a baseline config's trials can be reused when only one new config is added.
