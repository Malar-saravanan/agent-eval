# Experiment results

Raw exports from the running platform at the time of submission. These are the
exact responses of the public API endpoints used to produce the figures in
[`../experiment.md`](../experiment.md) and the screenshots in `../screenshots/`.

## Contents

| File | Produced by | Contents |
|---|---|---|
| `main-experiment.json` | `GET /api/experiments/<id>/export.json` | Full trace of every one of the 300 trials in the main experiment (`e_6a98d06c`): config, task, status, score, usage, cost, latency, final text, files, and the complete event stream. |
| `main-experiment.csv`  | `GET /api/experiments/<id>/export.csv`  | Flat view of the same 300 trials (status, score, cost, tokens, durations, reasoning). |
| `main-summary.json`    | `GET /api/experiments/<id>/summary`     | Per-config mean score with 95% bootstrap CI, infra/timeout/N-A counts, cost, latency, tokens. |
| `main-failures.json`   | `GET /api/experiments/<id>/failures`    | Rule-based failure classification for every failed trial. |
| `main-compare-plain-vs-full.json` | `GET /api/experiments/<id>/compare` | Paired comparison, score + cost + latency + tokens with CIs, McNemar, per-task deltas. |
| `main-compare-full-vs-opencode.json` | " | ↑ |
| `main-compare-plain-vs-opencode.json` | " | ↑ |
| `nudge-control.{json,csv}` | " | 70 trials of the nudge positive-control experiment (`e_e3a652f2`). |
| `nudge-summary.json`, `nudge-failures.json`, `nudge-compare-full-vs-nudge.json` | " | Companion endpoints for the control. |

## Reproducing

```bash
docker compose up --build        # UI + API on :3000
# Re-import these exports via the API is not supported; they are a snapshot.
# To regenerate from scratch, create the four configs described in the project
# README and launch the MAIN and CONTROL experiments. ~30 minutes, ~$5.95.
```

The schemas of these files match [`../api.md`](../api.md).
