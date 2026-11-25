# LLM judge validation

Judge model `gpt-4.1-mini`, temperature 0, JSON response. 30 hand-labelled samples (10 per judge task), each labelled per rubric criterion. Judge errors (unparseable or mis-shaped output) excluded: 0.

Agreement is the fraction of samples on which judge and human agree for that criterion. Cohen's kappa corrects for chance agreement; kappa is undefined when a rater is constant on a criterion.

---

## 14-summarize-readme (n = 10)

| # | criterion | agreement | kappa |
|---|-----------|-----------|-------|
| 1 | exactly three bullet points, nothing else | 60% | 0.31 |
| 2 | at least one bullet states what tinycache is or does | 100% | 1.00 |
| 3 | at least one bullet explains install or use | 100% | 1.00 |
| 4 | every claim supported by the README | 80% | 0.58 |

Task total: **agreement 85%, kappa 0.66.** Pass/fail verdict agreement: 70%, kappa 0.40.

## 15-commit-message (n = 10)

| # | criterion | agreement | kappa |
|---|-----------|-----------|-------|
| 1 | subject ≤ 50 characters | 90% | 0.62 |
| 2 | imperative mood, no trailing period | 70% | 0.35 |
| 3 | blank line between subject and body | 50% | 0.00 |
| 4 | message accurately describes the diff | 70% | 0.44 |

Task total: **agreement 70%, kappa 0.35.** Pass/fail verdict agreement: 50%, kappa 0.14.

## 16-explain-bug (n = 10)

| # | criterion | agreement | kappa |
|---|-----------|-----------|-------|
| 1 | identifies the root cause | 80% | 0.60 |
| 2 | describes the visible symptom | 90% | 0.78 |
| 3 | plain language for a non-programmer | 70% | 0.29 |
| 4 | proposes a correct fix | 90% | 0.80 |

Task total: **agreement 82%, kappa 0.64.** Pass/fail verdict agreement: 70%, kappa 0.44.

---

## Pooled

Over 120 criterion decisions: **agreement 79%, kappa 0.55.** 25 disagreements concentrated on counting (14 #1), whitespace and mood (15 #2–3), and "plain language" (16 #3).

## Reading

- Agreement is moderate overall and uneven across criteria.
- The judge is weakest on **mechanical** criteria (count bullets, require a blank line) — exactly where a deterministic grader would be strongest.
- The judge is strongest on **semantic** criteria (does the summary describe the thing? does the explanation name the root cause?).
- Self-preference risk is not neutralised: the judge is in the same model family as the subjects.
- Three of 20 tasks are judge-scored. Deterministic graders carry the headline numbers.
