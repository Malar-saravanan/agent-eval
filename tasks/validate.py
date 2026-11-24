"""Validate the sample task set.

For every task: schema check. For every non-judge task: (a) the untouched fixture must FAIL the grader and
(b) fixture + solution/ overlay must PASS. Run from anywhere:  python tasks/validate.py
"""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
TASKS = REPO / "tasks"
os.environ.setdefault("MODELS_FILE", str(REPO / "config" / "models.yaml"))
sys.path.insert(0, str(REPO / "worker"))
import graders  # noqa: E402

# the unit_tests grader invokes `python`; make sure it resolves to this interpreter
_shim = Path(tempfile.mkdtemp()) / "bin"
_shim.mkdir()
(_shim / "python").symlink_to(sys.executable)
os.environ["PATH"] = f"{_shim}{os.pathsep}{os.environ['PATH']}"

CATEGORIES = {"code", "fs", "exact", "judge", "skill", "memory"}
GRADERS = {"exact_match", "unit_tests", "fs_state", "llm_judge"}
REQUIRES = {"skills", "memory"}


def schema_errors(d: Path, t: dict) -> list[str]:
    e = []
    for k in ("id", "title", "category", "prompt", "grader", "limits"):
        if k not in t:
            e.append(f"missing {k}")
    if t.get("id") != d.name:
        e.append("id != dir name")
    if t.get("category") not in CATEGORIES:
        e.append("bad category")
    g = t.get("grader", {})
    if g.get("type") not in GRADERS:
        e.append("bad grader type")
    if g.get("type") == "unit_tests" and not (d / g.get("tests", "tests")).is_dir():
        e.append("tests dir missing")
    if g.get("type") == "llm_judge" and not (g.get("files") and g.get("rubric")):
        e.append("judge needs files + rubric")
    if g.get("type") == "exact_match" and "expected" not in g:
        e.append("exact_match needs expected")
    if not set(t.get("requires", [])) <= REQUIRES:
        e.append("bad requires")
    for s in t.get("setup", {}).get("skills", []):
        if not (d / "skills" / s / "SKILL.md").exists():
            e.append(f"skill {s} missing")
    if "skills" in t.get("requires", []) and not t.get("setup", {}).get("skills"):
        e.append("requires skills but no setup.skills")
    if "memory" in t.get("requires", []) and not t.get("setup", {}).get("memory_seed"):
        e.append("requires memory but no memory_seed")
    lim = t.get("limits", {})
    if not (lim.get("timeout_s") and lim.get("max_turns")):
        e.append("limits incomplete")
    return e


def grade(t, d, wd, final=""):
    return asyncio.run(graders.grade(t, d, wd, final))


def make_wd(d: Path, with_solution: bool) -> Path:
    wd = Path(tempfile.mkdtemp())
    if (d / "fixture").exists():
        shutil.copytree(d / "fixture", wd, dirs_exist_ok=True)
    if with_solution:
        sol = d / "solution"
        shutil.copytree(sol, wd, dirs_exist_ok=True)
        script = wd / "solve.sh"
        if script.exists():
            subprocess.run(["bash", "solve.sh"], cwd=wd, check=True)
            script.unlink(missing_ok=True)
    return wd


def main() -> int:
    rows, bad = [], 0
    for d in sorted(p for p in TASKS.iterdir() if p.is_dir() and p.name[:2].isdigit()):
        t = yaml.safe_load((d / "task.yaml").read_text())
        errs = schema_errors(d, t)
        if t["grader"]["type"] == "llm_judge" or t.get("category") == "judge":
            status = "schema-only"
            ok = not errs
            rows.append((d.name, t["category"], "ok" if ok else "ERR", "-", "-", status + (": " + "; ".join(errs) if errs else "")))
            bad += not ok
            continue
        expected = t["grader"].get("expected", "")
        final = f"ANSWER: {expected}" if t["grader"].get("source") == "final_answer" else ""
        pre = grade(t, d, make_wd(d, False), final if False else "")
        post = grade(t, d, make_wd(d, True), final)
        ok = not errs and not pre["passed"] and not pre["error"] and post["passed"]
        bad += not ok
        note = "; ".join(errs)
        if pre["passed"]:
            note += " fixture already passes!"
        if not post["passed"]:
            note += " solution fails: " + post["reasoning"][-300:].replace("\n", " ")
        rows.append((d.name, t["category"], "ok" if not errs else "ERR",
                     "FAIL(good)" if not pre["passed"] else "PASS(bad)", "PASS(good)" if post["passed"] else "FAIL(bad)", note))
    print(f"{'task':28} {'cat':7} {'schema':7} {'fixture':11} {'solution':11} notes")
    for r in rows:
        print(f"{r[0]:28} {r[1]:7} {r[2]:7} {r[3]:11} {r[4]:11} {r[5]}")
    print(f"\n{len(rows) - bad}/{len(rows)} green")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
