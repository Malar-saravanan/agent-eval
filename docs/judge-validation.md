# LLM judge validation

Judge model: `gpt-4.1-mini`, temperature 0. 30 hand-labelled samples (10 per judge task), each labelled per rubric criterion. Judge errors excluded: 0.

Raw agreement = fraction of samples where judge and human agree on that criterion. Cohen's kappa corrects for chance (n/a when a rater is constant on that criterion).

## 14-summarize-readme (n=10)

| # | criterion | agreement | kappa |
|---|---|---|---|
| 1 | summary.md contains exactly three bullet points (lines starting with '- ' or '* ') and no  | 60% | 0.31 |
| 2 | At least one bullet states what tinycache is or does (in-process caching of function resul | 100% | 1.00 |
| 3 | At least one bullet explains how to install or use it (the pip install command or the @cac | 100% | 1.00 |
| 4 | Every claim is supported by the README: no invented features, numbers or behaviour. | 80% | 0.58 |

Task total: agreement 85%, kappa 0.66

Overall pass/fail verdict agreement: 70%, kappa 0.40

## 15-commit-message (n=10)

| # | criterion | agreement | kappa |
|---|---|---|---|
| 1 | The first line (subject) is at most 50 characters long. | 90% | 0.62 |
| 2 | The subject is in the imperative mood (e.g. 'Add', 'Retry', 'Fix') and does not end with a | 70% | 0.35 |
| 3 | A blank line separates the subject from a non-empty body. | 50% | 0.00 |
| 4 | The message accurately describes the diff (retrying fetch_json on timeouts with exponentia | 70% | 0.44 |

Task total: agreement 70%, kappa 0.35

Overall pass/fail verdict agreement: 50%, kappa 0.14

## 16-explain-bug (n=10)

| # | criterion | agreement | kappa |
|---|---|---|---|
| 1 | Identifies the root cause: the default empty list is created only once and is shared by ev | 80% | 0.60 |
| 2 | Describes the visible symptom: items added to one cart (alice) also show up in the other c | 90% | 0.78 |
| 3 | Is written in plain language for a non-programmer: jargon is avoided or explained (an anal | 70% | 0.29 |
| 4 | Proposes a correct fix: use None as the default and create a new list inside the function  | 90% | 0.80 |

Task total: agreement 82%, kappa 0.64

Overall pass/fail verdict agreement: 70%, kappa 0.44

## Pooled (all criteria, all tasks)

Agreement 79% over 120 criterion decisions, Cohen's kappa 0.55

Disagreements (25): 14#c1, 14#c1, 14#c1, 14#c4, 14#c4, 14#c1, 15#c4, 15#c3, 15#c2, 15#c3, 15#c4, 15#c3, 15#c2, 15#c4, 15#c2, 15#c3, 15#c1, 15#c3, 16#c2, 16#c1, 16#c3, 16#c1, 16#c3, 16#c3, 16#c4
