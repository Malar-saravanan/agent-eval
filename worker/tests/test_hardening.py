"""Regression tests for the independent review: platform failures must never be scored as agent failures, state must
not leak between trials, and agents must not be able to reach /trial or use the gateway without a trial secret."""
import time

import pytest
from fastapi.testclient import TestClient

import app as worker_app
import harnesses
import meter
import trial
from harnesses import Harness, Result
from test_trial import FakeHarness, fake, ok_result, req, run  # noqa: F401  (fixtures/helpers shared with test_trial)


# ------------------------------------------------------------------ /trial access control
@pytest.fixture
def api(monkeypatch):
    calls = []

    async def fake_run(r):
        calls.append(r)
        return {"status": "passed"}
    monkeypatch.setattr(trial, "run_trial", fake_run)
    return TestClient(worker_app.app), calls


GOOD = {"trial_id": "t_abc", "task_id": "t1", "config": {}}


def test_trial_requires_the_worker_token(api):
    client, calls = api
    assert client.post("/trial", json=GOOD).status_code == 401
    assert client.post("/trial", json=GOOD, headers={"x-worker-token": "guess"}).status_code == 401
    assert client.post("/trial", json=GOOD, headers={"x-worker-token": ""}).status_code == 401
    assert calls == []                                           # nothing was started
    assert client.post("/trial", json=GOOD, headers={"x-worker-token": worker_app.WORKER_TOKEN}).status_code == 200


def test_health_and_gateway_do_not_need_the_trial_token(api):
    client, _ = api
    assert client.get("/health").json()["ok"] is True
    assert client.post("/v1/chat/completions", json={}).status_code == 401      # gateway has its own (per-trial) auth


def test_the_token_is_published_root_only(tmp_path, monkeypatch):
    f = tmp_path / "ipc" / "worker-token"
    monkeypatch.setattr(worker_app, "TOKEN_FILE", f)
    worker_app.publish_token()
    assert f.read_text() == worker_app.WORKER_TOKEN
    assert oct(f.stat().st_mode & 0o777) == "0o600" and oct(f.parent.stat().st_mode & 0o777) == "0o700"


@pytest.mark.parametrize("bad", ["../etc", "a/b", "", "x" * 65, "t 1", "t;rm", "..", "/abs"])
def test_ids_that_could_escape_the_runs_dir_are_rejected(task_env, fake, bad):
    task_env.write_task()
    fake()
    for field in ("trial_id", "task_id"):
        r = req()
        r[field] = bad
        with pytest.raises(ValueError):
            run(r)


def test_malformed_ids_are_http_400(monkeypatch):
    client = TestClient(worker_app.app)
    r = client.post("/trial", json={"trial_id": "../x", "task_id": "t1", "config": {}}, headers={"x-worker-token": worker_app.WORKER_TOKEN})
    assert r.status_code == 400


# ------------------------------------------------------------------ classification: platform failure != agent failure
def test_crash_after_partial_output_is_infra_not_a_failure(task_env, fake):
    task_env.write_task()
    fake(results=[Result([{"type": "assistant", "text": "I will start"}], "", False, -9, "Killed", complete=False)])
    out = run(req())
    assert out["status"] == "infra_error" and out["score"] is None and "terminated abnormally" in out["reasoning"]


def test_nonzero_exit_without_completion_marker_is_infra(task_env, fake):
    task_env.write_task()
    fake(results=[Result([{"type": "assistant", "text": "x"}], "", False, 1, "", complete=False)])
    assert run(req())["status"] == "infra_error"


def test_nonzero_exit_WITH_completion_marker_is_graded_normally(task_env, fake):
    """Hermes exits 1 for 'hit the iteration budget' but still emits its result event: that is the agent's outcome."""
    task_env.write_task()
    fake(results=[Result([{"type": "assistant", "text": "x"}], "ANSWER: 41", False, 1, "", complete=True)])
    assert run(req())["status"] == "failed"


def test_gateway_errors_make_a_failure_infra_but_never_demote_a_pass(task_env, monkeypatch):
    class Throttled(FakeHarness):
        def run(self, ctx):
            meter._record(ctx.trial_id, None, time.time(), error=True)   # a 429 the harness retried around
            return super().run(ctx)
    task_env.write_task()
    monkeypatch.setitem(harnesses.HARNESSES, "fake", Throttled(results=[ok_result("ANSWER: 41")]))
    bad = run(req(trial_id="a1"))
    assert bad["status"] == "infra_error" and "gateway error" in bad["reasoning"]
    monkeypatch.setitem(harnesses.HARNESSES, "fake", Throttled(results=[ok_result("ANSWER: 42")]))
    assert run(req(trial_id="a2"))["status"] == "passed"                  # solved despite throttling: still a pass


def test_budget_exhaustion_is_the_agents_outcome_even_if_errors_were_recorded(task_env, monkeypatch):
    class Spent(FakeHarness):
        def run(self, ctx):
            meter.EXHAUSTED[ctx.trial_id] = "steps"
            meter._record(ctx.trial_id, None, time.time(), error=True)
            return super().run(ctx)
    task_env.write_task()
    monkeypatch.setitem(harnesses.HARNESSES, "fake", Spent(results=[ok_result("ANSWER: 41")]))
    out = run(req())
    assert out["status"] == "failed"
    assert any(e.get("message", "").startswith("budget_exhausted") for e in out["events"])


# ------------------------------------------------------------------ state, concurrency, secrets
def test_gateway_secret_is_not_the_trial_id_and_is_released_afterwards(task_env, monkeypatch):
    seen = {}

    class Spy(FakeHarness):
        def run(self, ctx):
            seen["key"], seen["registered"] = ctx.key, meter.TOKENS.get(ctx.key)
            return super().run(ctx)
    task_env.write_task()
    monkeypatch.setitem(harnesses.HARNESSES, "fake", Spy())
    run(req(trial_id="tr_secret"))
    assert seen["key"] != "tr_secret" and len(seen["key"]) >= 24 and seen["registered"] == "tr_secret"
    assert seen["key"] not in meter.TOKENS                                 # unusable once the trial is over
    for store in (meter.USAGE, meter.BUDGETS, meter.EXHAUSTED, meter.RESOLVED, meter.OVERRIDES, meter.BASE):
        assert "tr_secret" not in store


def test_state_is_released_even_when_the_harness_raises(task_env, monkeypatch):
    class Boom(FakeHarness):
        def run(self, ctx):
            raise RuntimeError("harness exploded")
    task_env.write_task()
    monkeypatch.setitem(harnesses.HARNESSES, "fake", Boom())
    with pytest.raises(RuntimeError):
        run(req(trial_id="tr_boom"))
    assert "tr_boom" not in trial._active and not meter.TOKENS and "tr_boom" not in meter.BUDGETS
    assert not (task_env.runs / "tr_boom").exists()                        # run dir removed on failure too


def test_a_duplicate_of_a_running_trial_is_refused_without_touching_it(task_env, fake):
    task_env.write_task()
    h = fake()
    trial._active.add("tr_dup")
    try:
        out = run(req(trial_id="tr_dup"))
    finally:
        trial._active.discard("tr_dup")
    assert out["status"] == "infra_error" and "already running" in out["reasoning"]
    assert h.calls == []


def test_concurrent_trials_never_share_a_uid():
    got = [trial._alloc_uid() for _ in range(500)]
    assert len(set(got)) == 500
    for u in got:
        trial._uids.discard(u)


def test_task_phase_budget_restarts_after_the_memory_seed(task_env, monkeypatch):
    seen = {}

    class Seeded(FakeHarness):
        def run(self, ctx):
            if ctx.prompt.startswith("Remember"):
                meter.USAGE[ctx.trial_id]["steps"] += 5           # the seed used 5 steps
            else:
                seen["base"] = meter.BASE.get(ctx.trial_id)
            return super().run(ctx)

        def memory_saved(self, home):
            return True
    task_env.write_task(setup={"memory_seed": "Remember: x"})
    monkeypatch.setitem(harnesses.HARNESSES, "fake", Seeded(hit_gateway=True))
    run(req(memory=True))
    assert seen["base"][0] == 5                                    # task phase window starts after the seed's 5 steps


def test_non_object_json_lines_from_a_harness_are_skipped_not_fatal():
    assert list(harnesses._json_lines(['{"a":1}', "42", '"x"', "[1]", "not json", "null"])) == [{"a": 1}]


def test_install_skills_refuses_to_write_through_a_symlink(tmp_path):
    base = tmp_path / "home"; base.mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    (base / "skills").symlink_to(outside)                              # what a hostile seed session could plant
    skill = tmp_path / "skills_src" / "s1"; skill.mkdir(parents=True); (skill / "SKILL.md").write_text("x")
    with pytest.raises(OSError):
        harnesses.install_skills([str(skill)], base / "skills", base)
    assert list(outside.iterdir()) == []


def test_a_long_trial_keeps_the_http_response_alive_with_heartbeats(monkeypatch):
    """Node's fetch aborts after 300s without response headers; the API would then retry a trial the worker is still
    running. The worker streams whitespace heartbeats, then the JSON document."""
    import asyncio, json
    async def slow(r):
        await asyncio.sleep(0.35)
        return {"status": "passed", "trial_id": r["trial_id"]}
    monkeypatch.setattr(trial, "run_trial", slow)
    monkeypatch.setattr(worker_app, "HEARTBEAT_S", 0.1)
    r = TestClient(worker_app.app).post("/trial", json=GOOD, headers={"x-worker-token": worker_app.WORKER_TOKEN})
    assert r.status_code == 200
    assert r.content.startswith(b"  ")                      # at least two heartbeats arrived before the result
    assert json.loads(r.content) == {"status": "passed", "trial_id": "t_abc"}   # whitespace + JSON parses as JSON


def test_a_crashing_trial_still_returns_a_visible_infra_error(monkeypatch):
    import json
    async def boom(r):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(trial, "run_trial", boom)
    r = TestClient(worker_app.app).post("/trial", json=GOOD, headers={"x-worker-token": worker_app.WORKER_TOKEN})
    out = json.loads(r.content)
    assert out["status"] == "infra_error" and "kaboom" in out["reasoning"]
