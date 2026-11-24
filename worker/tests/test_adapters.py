import asyncio
import json

import pytest

import harnesses
import trial
from conftest import record_gateway_call
from harnesses import Ctx, Harness, Hermes, OpenCode, Result


def lines(*events):
    """Canned CLI stdout: dicts become JSON lines, strings are kept verbatim (noise)."""
    return [e if isinstance(e, str) else json.dumps(e) for e in events]


@pytest.fixture
def ctx(tmp_path):
    work, home = tmp_path / "work", tmp_path / "home"
    work.mkdir(), home.mkdir()
    (work / ".git").mkdir()          # makes OpenCode skip `git init`
    return Ctx("tr1", "do it", work, home, "gpt-4.1-mini", 5, 30, uid=None)


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """Replace the subprocess runner: adapters parse whatever stdout we hand them."""
    monkeypatch.setattr(harnesses, "TEMPLATE", tmp_path / "template")
    (tmp_path / "template").mkdir()
    seen = {}

    def install(out, timed_out=False, code=0, err=""):
        def fake_run(cmd, c, env):
            seen.update(cmd=cmd, env=env)
            return out, timed_out, code, err
        monkeypatch.setattr(harnesses, "_run", fake_run)
        return seen
    return install


# ---------------------------------------------------------------- Hermes
HERMES_OUT = lines(
    {"type": "system", "subtype": "init", "session_id": "s"},
    {"type": "tool_use", "tool_call_id": "c1", "name": "skill_view", "input": {"name": "changelog"}},
    {"type": "tool_result", "tool_call_id": "c1", "name": "skill_view", "output": "SKILL TEXT", "is_error": False},
    {"type": "tool_use", "tool_call_id": "c2", "name": "memory", "input": {"action": "add"}},
    {"type": "tool_result", "tool_call_id": "c2", "name": "memory", "output": {"ok": 1}, "is_error": True},
    {"type": "tool_use", "tool_call_id": "c3", "name": "terminal", "input": {"command": "ls"}},
    "this is not json",
    "",
    {"type": "text", "text": "Hel"}, {"type": "text", "text": "lo "}, {"type": "text", "text": "world"},
    "{truncated json",
    {"type": "result", "text": "Hello world"},
)


class TestHermes:
    def test_normalises_events(self, ctx, cli):
        cli(HERMES_OUT)
        r = Hermes().run(ctx)
        assert [e["type"] for e in r.events] == ["tool_call", "tool_result", "tool_call", "tool_result", "tool_call", "assistant"]
        calls = [e for e in r.events if e["type"] == "tool_call"]
        assert [(c["name"], c["kind"]) for c in calls] == [("skill_view", "skill"), ("memory", "memory"), ("terminal", "tool")]
        assert calls[0]["id"] == "c1" and calls[0]["input"] == {"name": "changelog"}
        results = [e for e in r.events if e["type"] == "tool_result"]
        assert [x["error"] for x in results] == [False, True]
        assert results[1]["output"] == "{'ok': 1}"          # non-string output is stringified
        assert r.final_text == "Hello world"
        assert not r.timed_out and r.exit_code == 0

    def test_text_deltas_merge_into_one_assistant_event(self, ctx, cli):
        cli(HERMES_OUT)
        assistants = [e for e in Hermes().run(ctx).events if e["type"] == "assistant"]
        assert assistants == [{"type": "assistant", "text": "Hello world"}]

    def test_text_after_a_tool_starts_a_new_message(self, ctx, cli):
        cli(lines({"type": "text", "text": "a"}, ) + lines({"type": "tool_use", "tool_call_id": "1", "name": "t", "input": {}},
                                                           {"type": "text", "text": "b"}, {"type": "text", "text": "c"}))
        ev = Hermes().run(ctx).events
        assert [e["type"] for e in ev] == ["assistant", "tool_call", "assistant"]
        assert [e.get("text") for e in ev if e["type"] == "assistant"] == ["a", "bc"]

    def test_result_error_becomes_error_event(self, ctx, cli):
        cli(lines({"type": "result", "text": "", "error": "max turns reached"}))
        r = Hermes().run(ctx)
        assert r.events == [{"type": "error", "message": "max turns reached"}]

    def test_only_garbage_yields_empty_result(self, ctx, cli):
        cli(["garbage", "<html>", ""], code=1, err="boom")
        r = Hermes().run(ctx)
        assert r.events == [] and r.final_text == "" and r.exit_code == 1 and r.stderr == "boom"

    def test_long_tool_output_truncated(self, ctx, cli):
        cli(lines({"type": "tool_result", "tool_call_id": "1", "name": "t", "output": "x" * 9000}))
        assert len(Hermes().run(ctx).events[0]["output"]) == 4000

    def test_timeout_flag_propagates_and_env_uses_trial_id_as_key(self, ctx, cli):
        seen = cli([], timed_out=True, code=-1)
        r = Hermes().run(ctx)
        assert r.timed_out and r.exit_code == -1
        assert seen["env"]["OPENAI_API_KEY"] == "tr1" and seen["env"]["HERMES_HOME"] == str(ctx.home)
        assert "--max-turns" in seen["cmd"] and seen["cmd"][seen["cmd"].index("--max-turns") + 1] == "5"

    def test_skills_copied_into_home(self, ctx, cli, tmp_path):
        skill = tmp_path / "src" / "changelog"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("s")
        cli([])
        ctx.skills = [str(skill)]
        Hermes().run(ctx)
        assert (ctx.home / "skills" / "changelog" / "SKILL.md").read_text() == "s"


# ---------------------------------------------------------------- OpenCode
OPENCODE_OUT = lines(
    {"type": "step_start", "part": {"type": "step-start"}},
    {"type": "tool_use", "part": {"tool": "bash", "callID": "k1",
                                  "state": {"status": "completed", "input": {"command": "ls"}, "output": "a.txt"}}},
    {"type": "tool_use", "part": {"tool": "skill", "callID": "k2",
                                  "state": {"status": "error", "input": {"name": "x"}, "error": "no such skill"}}},
    "WARN not json",
    {"type": "text", "part": {"text": "first"}},
    {"type": "step_finish", "part": {}},
    {"type": "step_start", "part": {}},
    {"type": "text", "part": {"text": "all done"}},
    {"type": "step_finish", "part": {}},
)


class TestOpenCode:
    def test_normalises_events(self, ctx, cli):
        cli(OPENCODE_OUT)
        r = OpenCode().run(ctx)
        assert [e["type"] for e in r.events] == ["tool_call", "tool_result", "tool_call", "tool_result", "assistant", "assistant"]
        c1, r1, c2, r2 = r.events[:4]
        assert (c1["name"], c1["kind"], c1["id"], c1["input"]) == ("bash", "tool", "k1", {"command": "ls"})
        assert (r1["output"], r1["error"]) == ("a.txt", False)
        assert (c2["name"], c2["kind"]) == ("skill", "skill")
        assert (r2["output"], r2["error"]) == ("no such skill", True)

    def test_final_text_is_last_text_part(self, ctx, cli):
        cli(OPENCODE_OUT)
        assert OpenCode().run(ctx).final_text == "all done"

    def test_step_limit_enforced_after_the_fact(self, ctx, cli):
        cli(OPENCODE_OUT)
        ctx.max_turns = 1                       # two step_finish events > 1
        errs = [e for e in OpenCode().run(ctx).events if e["type"] == "error"]
        assert errs == [{"type": "error", "message": "step_limit: 2 > 1"}]
        ctx.max_turns = 2
        assert not [e for e in OpenCode().run(ctx).events if e["type"] == "error"]

    def test_memory_tool_name_is_kind_memory(self, ctx, cli):
        cli(lines({"type": "tool_use", "part": {"tool": "memory_save", "callID": "m", "state": {"status": "completed"}}}))
        assert OpenCode().run(ctx).events[0]["kind"] == "memory"

    def test_garbage_only_and_no_text(self, ctx, cli):
        cli(["nope", "{bad"], code=2, err="e")
        r = OpenCode().run(ctx)
        assert r.events == [] and r.final_text == "" and r.exit_code == 2

    def test_writes_config_pointing_at_gateway_with_trial_key(self, ctx, cli):
        seen = cli([])
        OpenCode().run(ctx)
        cfg = json.loads((ctx.home / "opencode.json").read_text())
        assert cfg["model"] == "proxy/gpt-4.1-mini"
        assert cfg["provider"]["proxy"]["options"]["baseURL"] == harnesses.BASE_URL
        assert seen["env"]["EVAL_TRIAL_ID"] == "tr1"
        assert seen["cmd"][:2] == ["opencode", "run"] and seen["cmd"][-2:] == ["--format", "json"]

    def test_skills_installed_into_workdir(self, ctx, cli, tmp_path):
        skill = tmp_path / "src" / "lint"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("s")
        cli([])
        ctx.skills = [str(skill)]
        OpenCode().run(ctx)
        assert (ctx.workdir / ".opencode" / "skills" / "lint" / "SKILL.md").exists()


def test_capabilities():
    assert Hermes.capabilities == {"skills", "memory"} and OpenCode.capabilities == {"skills"}
    assert set(harnesses.HARNESSES) >= {"hermes", "opencode"}


# ---------------------------------------------------------------- registry: new harness = one adapter
def test_new_harness_runs_through_trial_with_zero_other_changes(task_env, monkeypatch):
    class Dummy(Harness):
        name = "dummy"
        capabilities = {"skills"}

        def run(self, ctx):
            record_gateway_call(ctx.trial_id)
            (ctx.workdir / "answer.txt").write_text("42")
            return Result([{"type": "assistant", "text": "done"}], "ok")

    monkeypatch.setitem(harnesses.HARNESSES, "dummy", Dummy())
    task_env.write_task(grader={"type": "fs_state", "checks": [{"file_contains": ["answer.txt", "42"]}]})
    out = asyncio.run(trial.run_trial({"trial_id": "d1", "task_id": "t1",
                                       "config": {"harness": "dummy", "model": "gpt-4.1-mini", "settings": {}}}))
    assert out["status"] == "passed" and out["score"] == 1.0
    assert out["meta"]["harness_version"] is None      # unknown version is recorded, not fatal
    # capability gating also works for the new adapter
    task_env.write_task("t2", requires=["memory"], setup={"memory_seed": "s"})
    out = asyncio.run(trial.run_trial({"trial_id": "d2", "task_id": "t2",
                                       "config": {"harness": "dummy", "model": "gpt-4.1-mini", "settings": {}}}))
    assert out["status"] == "not_applicable"
