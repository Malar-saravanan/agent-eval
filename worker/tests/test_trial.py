import asyncio

import pytest

import harnesses
import meter
import trial
from conftest import record_gateway_call
from harnesses import Harness, Result


class FakeHarness(Harness):
    """Scriptable stand-in for a real CLI: records every invocation and returns canned results."""
    name = "fake"
    capabilities = {"skills", "memory"}

    def __init__(self, results=None, hit_gateway=True, capabilities=None):
        self.results = list(results or [])
        self.hit_gateway = hit_gateway
        self.calls = []
        if capabilities is not None:
            self.capabilities = capabilities

    def run(self, ctx):
        self.calls.append({"ctx": ctx, "budget": dict(meter.BUDGETS.get(ctx.trial_id) or {}),
                           "override": dict(meter.OVERRIDES.get(ctx.trial_id) or {}),
                           "work_files": sorted(p.name for p in ctx.workdir.iterdir())})
        if self.hit_gateway:
            record_gateway_call(ctx.trial_id)
        return self.results.pop(0) if self.results else ok_result("ANSWER: 42")


def ok_result(final="ANSWER: 42", events=None):
    return Result(events if events is not None else [{"type": "assistant", "text": "thinking"}], final)


@pytest.fixture
def fake(monkeypatch):
    def install(**kw):
        h = FakeHarness(**kw)
        monkeypatch.setitem(harnesses.HARNESSES, "fake", h)
        return h
    return install


def req(task_id="t1", trial_id="tr1", **settings):
    return {"trial_id": trial_id, "task_id": task_id,
            "config": {"harness": "fake", "model": "gpt-4.1-mini", "settings": settings}}


def run(r):
    return asyncio.run(trial.run_trial(r))


# ---------------------------------------------------------------- classification
def test_no_events_and_oom_exit_is_infra_error_never_scored(task_env, fake):
    task_env.write_task()
    fake(results=[Result([], "", False, 137, "Killed")])
    out = run(req())
    assert out["status"] == "infra_error" and out["score"] is None
    assert "exit 137" in out["reasoning"] and "Killed" in out["reasoning"]


def test_gateway_never_called_is_infra_error(task_env, fake):
    task_env.write_task()
    fake(hit_gateway=False)
    out = run(req())
    assert out["status"] == "infra_error" and out["score"] is None and "gateway never called" in out["reasoning"]


def test_timeout_scores_zero(task_env, fake):
    task_env.write_task(limits={"timeout_s": 5, "max_turns": 5})
    fake(results=[Result([], "", True, -1, "")])
    out = run(req())
    assert out["status"] == "timeout" and out["score"] == 0.0 and "5s" in out["reasoning"]


def test_timeout_with_partial_progress_is_still_timeout(task_env, fake):
    task_env.write_task()
    fake(results=[Result([{"type": "assistant", "text": "x"}], "ANSWER: 42", True, -1, "")])
    assert run(req())["status"] == "timeout"


def test_graded_pass_and_fail(task_env, fake):
    task_env.write_task()
    fake(results=[ok_result("ANSWER: 42"), ok_result("ANSWER: 7")])
    good, bad = run(req(trial_id="a")), run(req(trial_id="b"))
    assert (good["status"], good["score"]) == ("passed", 1.0)
    assert (bad["status"], bad["score"]) == ("failed", 0.0)
    assert good["events"][-1]["type"] == "grade" and good["events"][-1]["passed"] is True
    assert good["final_text"] == "ANSWER: 42"


def test_grader_error_is_neither_pass_nor_fail(task_env, fake):
    task_env.write_task(grader={"type": "bogus"})
    fake()
    out = run(req())
    assert out["status"] == "grader_error" and out["score"] is None


def test_usage_and_cost_reported(task_env, fake):
    task_env.write_task()
    fake()
    out = run(req())
    assert out["usage"]["prompt_tokens"] == 10 and out["usage"]["completion_tokens"] == 5 and out["usage"]["calls"] == 1
    assert out["cost_usd"] == pytest.approx((10 * 0.40 + 5 * 1.60) / 1e6, abs=1e-6)
    assert "tr1" not in meter.USAGE   # per-trial meter state cleaned up


def test_retry_does_not_inherit_failed_attempts_usage(task_env, fake):
    task_env.write_task()
    fake()
    meter._record("tr1", {"prompt_tokens": 999, "completion_tokens": 999}, 0)   # leftovers of a crashed attempt
    assert run(req())["usage"]["prompt_tokens"] == 10


# ---------------------------------------------------------------- capabilities
def test_missing_capability_is_not_applicable_and_harness_not_invoked(task_env, fake):
    task_env.write_task(requires=["memory"], setup={"memory_seed": "remember x"})
    h = fake(capabilities={"skills"})
    out = run(req(memory=True))
    assert out["status"] == "not_applicable" and out["score"] is None and h.calls == []


# ---------------------------------------------------------------- memory seed / skills
def test_memory_seed_runs_only_when_memory_setting_on(task_env, fake):
    task_env.write_task(setup={"memory_seed": "Remember: port 8081"})
    h = fake(results=[ok_result("noted", [{"type": "assistant", "text": "noted"}]), ok_result()])
    out = run(req(memory=True))
    assert [c["ctx"].prompt for c in h.calls] == ["Remember: port 8081", "Say 42."]
    assert h.calls[0]["ctx"].workdir != h.calls[1]["ctx"].workdir      # seed gets its own scratch dir
    assert h.calls[0]["ctx"].home == h.calls[1]["ctx"].home            # ...but shares the memory state dir
    assert [e.get("phase") for e in out["events"] if e["type"] == "assistant"] == ["seed", "task"]

    h2 = fake()
    run(req(trial_id="tr2", memory=False))
    assert [c["ctx"].prompt for c in h2.calls] == ["Say 42."]


class UnreliableMemory(FakeHarness):
    """Memory is persisted only on the Nth seed attempt (the agent sometimes calls the tool without anything saving)."""
    def __init__(self, saved_on):
        super().__init__()
        self.saved_on, self.seeds = saved_on, 0

    def run(self, ctx):
        if ctx.prompt.startswith("Remember"):
            self.seeds += 1
        return super().run(ctx)

    def memory_saved(self, home):
        return self.seeds >= self.saved_on


def test_memory_seed_is_retried_until_the_fact_is_saved(task_env, monkeypatch):
    task_env.write_task(setup={"memory_seed": "Remember: port 8081"})
    h = UnreliableMemory(saved_on=2)
    monkeypatch.setitem(harnesses.HARNESSES, "fake", h)
    out = run(req(memory=True))
    assert h.seeds == 2 and [c["ctx"].prompt for c in h.calls][-1] == "Say 42."
    assert not [e for e in out["events"] if e["type"] == "error"]


def test_memory_seed_gives_up_after_three_attempts_and_says_so(task_env, monkeypatch):
    task_env.write_task(setup={"memory_seed": "Remember: port 8081"})
    h = UnreliableMemory(saved_on=99)
    monkeypatch.setitem(harnesses.HARNESSES, "fake", h)
    out = run(req(memory=True))
    assert h.seeds == 3
    assert any(e["type"] == "error" and e["message"].startswith("memory_seed_unsaved") for e in out["events"])
    assert out["status"] != "infra_error"            # the agent not saving is its behaviour, not an infra failure


def test_skills_installed_only_when_skills_setting_on(task_env, fake):
    d = task_env.write_task(setup={"skills": ["changelog"]})
    (d / "skills" / "changelog").mkdir(parents=True)
    (d / "skills" / "changelog" / "SKILL.md").write_text("x")
    h = fake()
    run(req(skills=True))
    run(req(trial_id="tr2", skills=False))
    assert h.calls[0]["ctx"].skills == [str(d / "skills" / "changelog")]
    assert h.calls[1]["ctx"].skills == []


# ---------------------------------------------------------------- budgets
def test_budgets_and_temperature_come_from_settings_and_are_cleaned_up(task_env, fake):
    task_env.write_task(limits={"timeout_s": 30, "max_turns": 20})
    h = fake()
    out = run(req(max_turns=7, token_budget=1234, temperature=0.0))
    assert h.calls[0]["budget"] == {"max_steps": 7, "max_tokens": 1234}
    assert h.calls[0]["override"] == {"temperature": 0.0}
    assert h.calls[0]["ctx"].max_turns == 7 and h.calls[0]["ctx"].timeout_s == 30
    assert out["meta"]["budget"] == {"max_steps": 7, "max_tokens": 1234}
    assert not meter.BUDGETS and not meter.OVERRIDES


def test_task_limit_caps_requested_max_turns_and_defaults_apply(task_env, fake):
    task_env.write_task(limits={"timeout_s": 30, "max_turns": 5})
    h = fake()
    run(req(max_turns=50))
    assert h.calls[0]["budget"] == {"max_steps": 5, "max_tokens": 300_000}
    assert h.calls[0]["override"] == {}


def test_exhausted_budget_appends_error_event(task_env, fake):
    task_env.write_task()

    class Exhausting(FakeHarness):
        def run(self, ctx):
            meter.EXHAUSTED[ctx.trial_id] = "steps"
            return super().run(ctx)
    h = Exhausting()
    harnesses.HARNESSES["fake"] = h
    try:
        out = run(req())
    finally:
        del harnesses.HARNESSES["fake"]
    errs = [e for e in out["events"] if e["type"] == "error"]
    assert errs == [{"type": "error", "message": "budget_exhausted: steps", "phase": "task"}]
    assert "tr1" not in meter.EXHAUSTED


# ---------------------------------------------------------------- isolation
def test_fresh_workdir_per_trial_and_run_dir_removed(task_env, fake):
    d = task_env.write_task()
    (d / "fixture").mkdir()
    (d / "fixture" / "seed.txt").write_text("fixture")

    class Littering(FakeHarness):
        def run(self, ctx):
            (ctx.workdir / "leftover.txt").write_text("from trial 1")
            return super().run(ctx)
    harnesses.HARNESSES["fake"] = Littering()
    try:
        run(req(trial_id="one"))
        h2 = FakeHarness()
        harnesses.HARNESSES["fake"] = h2
        run(req(trial_id="two"))
    finally:
        del harnesses.HARNESSES["fake"]
    assert h2.calls[0]["work_files"] == ["seed.txt"]          # fixture present, trial 1's file is not
    assert not (task_env.runs / "one").exists() and not (task_env.runs / "two").exists()


def test_rerun_of_same_trial_id_starts_clean(task_env, fake):
    task_env.write_task()
    stale = task_env.runs / "tr1" / "work"
    stale.mkdir(parents=True)
    (stale / "stale.txt").write_text("from crashed attempt")
    h = fake()
    run(req())
    assert h.calls[0]["work_files"] == []


def test_workdir_files_listed_in_output(task_env, fake):
    task_env.write_task()

    class Writer(FakeHarness):
        def run(self, ctx):
            (ctx.workdir / "out.txt").write_text("x")
            (ctx.workdir / ".git").mkdir()
            return super().run(ctx)
    harnesses.HARNESSES["fake"] = Writer()
    try:
        out = run(req())
    finally:
        del harnesses.HARNESSES["fake"]
    assert out["files"] == ["out.txt"]


# ---------------------------------------------------------------- meta / nudge
def test_meta_has_provenance(task_env, fake):
    d = task_env.write_task()
    fake()
    out = run(req(nudge=True, max_turns=9))
    m = out["meta"]
    assert m["task_hash"] == trial.task_hash(d) and len(m["task_hash"]) == 12
    assert "harness_version" in m and m["harness_version"] == "9.9.9"
    assert m["budget"] == {"max_steps": 9, "max_tokens": 300_000}
    assert m["nudge"] is True and m["model_deployment"] == "dep-mini"
    assert run(req(trial_id="tr2"))["meta"]["nudge"] is False


def test_task_hash_changes_with_content(task_env):
    d = task_env.write_task()
    h1 = trial.task_hash(d)
    assert trial.task_hash(d) == h1
    (d / "task.yaml").write_text((d / "task.yaml").read_text() + "\n# edit\n")
    assert trial.task_hash(d) != h1


def test_resolved_model_lands_in_meta(task_env, fake):
    task_env.write_task()

    class Resolving(FakeHarness):
        def run(self, ctx):
            meter.RESOLVED[ctx.trial_id] = "gpt-4.1-mini-2025-04-14"
            return super().run(ctx)
    harnesses.HARNESSES["fake"] = Resolving()
    try:
        out = run(req())
    finally:
        del harnesses.HARNESSES["fake"]
    assert out["meta"]["model_resolved"] == "gpt-4.1-mini-2025-04-14"


def test_nudge_only_when_enabled(task_env, fake):
    task_env.write_task()
    h = fake()
    run(req(nudge=True))
    run(req(trial_id="tr2", nudge=False))
    run(req(trial_id="tr3"))
    assert h.calls[0]["ctx"].prompt == "Say 42." + trial.NUDGE
    assert h.calls[1]["ctx"].prompt == "Say 42." and h.calls[2]["ctx"].prompt == "Say 42."


def test_unknown_harness_raises_keyerror(task_env):
    task_env.write_task()
    r = req()
    r["config"]["harness"] = "ghost"
    with pytest.raises(KeyError):
        run(r)
