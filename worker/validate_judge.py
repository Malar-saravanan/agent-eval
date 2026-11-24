"""Measure the LLM judge against hand labels (tasks/judge-labels.json).

Run from the repo root:  python worker/validate_judge.py
Needs the AZURE_* / MODEL1_DEPLOYMENT vars from .env. Costs real API calls (one per labelled sample).
Writes docs/judge-validation.md (+ docs/judge-validation.json with raw judge verdicts).
"""
import asyncio
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
os.environ.setdefault("MODELS_FILE", str(REPO / "config" / "models.yaml"))
for line in (REPO / ".env").read_text().splitlines():  # tiny .env parser
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import graders  # noqa: E402


def kappa(a: list[bool], b: list[bool]):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if pe == 1:
        return None if po < 1 else 1.0  # undefined when both raters are constant; perfect if they agree
    return (po - pe) / (1 - pe)


def fmt(k):
    return "n/a" if k is None else f"{k:.2f}"


async def main():
    samples = json.loads((REPO / "tasks" / "judge-labels.json").read_text())
    tasks = {}
    results = []  # (task_id, human[], judge[]|None, reasoning)
    for s in samples:
        tid = s["task_id"]
        if tid not in tasks:
            tasks[tid] = yaml.safe_load((REPO / "tasks" / tid / "task.yaml").read_text())
        t = tasks[tid]
        g = t["grader"]
        with tempfile.TemporaryDirectory() as wd:
            wd = Path(wd)
            for f in g["files"]:
                (wd / f).write_text(s["response"])
            res = await graders.llm_judge(g, t, wd, "")
        judge = None
        if not res["error"]:
            crit = sorted(json.loads(res["reasoning"]), key=lambda c: c["id"])
            judge = [bool(c["pass"]) for c in crit]
        results.append({"task_id": tid, "human": s["human"], "judge": judge, "reasoning": res["reasoning"]})
        print(tid, s["human"], judge, flush=True)

    (REPO / "docs" / "judge-validation.json").write_text(json.dumps(results, indent=1))
    by_task = defaultdict(list)
    for r in results:
        if r["judge"] is not None:
            by_task[r["task_id"]].append(r)
    errors = sum(r["judge"] is None for r in results)

    out = ["# LLM judge validation", "",
           f"Judge model: `{os.environ.get('JUDGE_MODEL') or next(iter(graders.meter.MODELS))}`, temperature 0. "
           f"{len(results)} hand-labelled samples (10 per judge task), each labelled per rubric criterion. "
           f"Judge errors excluded: {errors}.", "",
           "Raw agreement = fraction of samples where judge and human agree on that criterion. "
           "Cohen's kappa corrects for chance (n/a when a rater is constant on that criterion).", ""]
    all_h, all_j = [], []
    for tid, rs in by_task.items():
        rubric = tasks[tid]["grader"]["rubric"]
        out += [f"## {tid} (n={len(rs)})", "", "| # | criterion | agreement | kappa |", "|---|---|---|---|"]
        th, tj = [], []
        for i, crit in enumerate(rubric):
            h = [r["human"][i] for r in rs]
            j = [r["judge"][i] for r in rs]
            th += h
            tj += j
            agree = sum(x == y for x, y in zip(h, j)) / len(h)
            out.append(f"| {i + 1} | {crit[:90]} | {agree:.0%} | {fmt(kappa(h, j))} |")
        agree = sum(x == y for x, y in zip(th, tj)) / len(th)
        out += ["", f"Task total: agreement {agree:.0%}, kappa {fmt(kappa(th, tj))}", ""]
        # sample-level pass/fail (threshold 0.75 = at least 3 of 4 criteria)
        hp = [sum(r["human"]) / len(r["human"]) >= 0.75 for r in rs]
        jp = [sum(r["judge"]) / len(r["judge"]) >= 0.75 for r in rs]
        out += [f"Overall pass/fail verdict agreement: {sum(a == b for a, b in zip(hp, jp)) / len(hp):.0%}, "
                f"kappa {fmt(kappa(hp, jp))}", ""]
        all_h += th
        all_j += tj
    if all_h:
        out += ["## Pooled (all criteria, all tasks)", "",
                f"Agreement {sum(a == b for a, b in zip(all_h, all_j)) / len(all_h):.0%} over {len(all_h)} criterion "
                f"decisions, Cohen's kappa {fmt(kappa(all_h, all_j))}", ""]
        dis = [(r["task_id"], i + 1) for r in results if r["judge"] for i, (a, b) in enumerate(zip(r["human"], r["judge"])) if a != b]
        out += [f"Disagreements ({len(dis)}): " + ", ".join(f"{t.split('-')[0]}#c{c}" for t, c in dis), ""]
    (REPO / "docs" / "judge-validation.md").write_text("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    asyncio.run(main())
