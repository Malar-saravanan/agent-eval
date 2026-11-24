"""Harness adapters. To add a harness: subclass Harness, implement run(), add it to HARNESSES.

Every adapter must translate its native output into the common trace event shape:
  {"type": "assistant", "text"}
  {"type": "tool_call",   "id", "name", "input", "kind": "tool|skill|memory"}
  {"type": "tool_result", "id", "name", "output", "error": bool}
  {"type": "error", "message"}
"""
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import meter

BASE_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000/v1")
WARM_MODEL = os.environ.get("WARM_MODEL", "gpt-4.1-mini")
XDG_CACHE = os.environ.get("XDG_CACHE_HOME", "/opt/cache")   # shared package cache, writable by every trial user


@dataclass
class Ctx:
    trial_id: str
    prompt: str
    workdir: Path
    home: Path                 # per-trial harness state dir (memory, sessions, skills)
    model: str
    max_turns: int
    timeout_s: int
    skills: list = field(default_factory=list)   # skill dirs to install (empty = skills off)
    uid: int | None = None     # unprivileged uid the agent runs as (None = current user, used only for warm-up)
    api_key: str | None = None  # gateway bearer secret issued by meter.register(); defaults to trial_id (tests / warm-up)

    @property
    def key(self) -> str:
        return self.api_key or self.trial_id


@dataclass
class Result:
    events: list
    final_text: str
    timed_out: bool = False
    exit_code: int = 0
    stderr: str = ""
    complete: bool = True   # did the harness reach its own normal end-of-run marker?


SKILL_READ = {"skill", "skill_view", "skills_list", "skills_search"}   # consulting a skill; skill_manage EDITS skills, it is not use


def _kind(name: str) -> str:
    n = name.lower()
    return "skill" if n in SKILL_READ else "memory" if "memory" in n else "tool"


def reap_all(marker: str, uid: int | None):
    """reap() until nothing is left: a daemon that forks or respawns while we scan must not survive."""
    for _ in range(10):
        if not reap(marker, uid):
            return
        time.sleep(0.1)


def reap(marker: str, uid: int | None = None) -> int:
    """Kill every process left behind by a trial. Hermes leaves ~300MB `gateway` daemons running after each run; they do
    not carry the trial id in their environment, so with a per-trial uid we kill by owner (exact), falling back to the
    environment marker when there is no uid (warm-up). Unreaped, they exhaust memory and later trials get OOM-killed."""
    if not os.path.isdir("/proc"):   # non-Linux dev machine: nothing to scan
        return 0
    mark, me, killed = marker.encode(), os.getpid(), 0
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            if int(pid) == me:
                continue
            if uid is not None:
                owner = int([l for l in open(f"/proc/{pid}/status") if l.startswith("Uid:")][0].split()[1])
                hit = owner == uid
            else:
                hit = mark in open(f"/proc/{pid}/environ", "rb").read()
            if hit:
                os.kill(int(pid), signal.SIGKILL)
                killed += 1
        except (OSError, IndexError):
            continue
    return killed


SAFE_ENV = ("PATH", "LANG", "LC_ALL", "TERM", "TZ")   # nothing else from the worker env (it holds the Azure key)
VERSIONS: dict = {}                                    # harness name -> version string, filled at warm-up


def install_skills(skills: list, dst_root: Path, base: Path):
    """Copy skill dirs under dst_root, refusing to write through a symlink. Runs as root into a directory an earlier
    agent session (the memory seed) may have touched, so a planted symlink must never redirect the copy."""
    if os.path.lexists(dst_root) and (os.path.islink(dst_root) or not os.path.realpath(dst_root).startswith(os.path.realpath(base) + os.sep)):
        raise OSError(f"refusing to install skills through a symlink: {dst_root}")
    for s_ in skills:
        dst = dst_root / Path(s_).name
        if os.path.lexists(dst) and os.path.islink(dst):
            raise OSError(f"refusing to install skills through a symlink: {dst}")
        shutil.copytree(s_, dst, dirs_exist_ok=True, symlinks=True)


def chown_tree(path: Path, uid: int | None):
    """Give an unprivileged agent ownership of a directory tree (symlinks themselves, never their targets)."""
    if uid is None:
        return
    for root, dirs, files in os.walk(path, followlinks=False):
        for n in [root, *[os.path.join(root, x) for x in dirs + files]]:
            os.lchown(n, uid, uid)


def _run(cmd, ctx: Ctx, env: dict):
    """Run a harness CLI as the trial's unprivileged user, in its own process group, with a scrubbed environment.
    Output goes to temp files (not pipes): a daemon that inherits the pipe could otherwise keep communicate() blocked
    after the harness exits. Returns (stdout_lines, timed_out, exit_code, stderr_tail)."""
    clean = {k: os.environ[k] for k in SAFE_ENV if k in os.environ}
    clean["HOME"] = str(ctx.home)
    ids = {"user": ctx.uid, "group": ctx.uid} if ctx.uid is not None else {}
    with tempfile.TemporaryFile("w+") as fout, tempfile.TemporaryFile("w+") as ferr:
        p = subprocess.Popen(cmd, cwd=ctx.workdir, env={**clean, **env}, stdout=fout, stderr=ferr,
                             text=True, start_new_session=True, **ids)
        timed_out = False
        try:
            p.wait(timeout=ctx.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
        finally:
            reap_all(ctx.trial_id, ctx.uid)
        fout.seek(0)
        ferr.seek(0)
        out, err = fout.read(), ferr.read()
    return out.splitlines(), timed_out, (-1 if timed_out else p.returncode), err[-400:]


def _json_lines(lines):
    for l in lines:
        try:
            e = json.loads(l)
        except ValueError:
            continue
        if isinstance(e, dict):   # a bare number/list/string line is not an event
            yield e


TEMPLATE = Path(os.environ.get("HERMES_TEMPLATE", "/opt/hermes-template"))
SHARED = ("installs", "cache")      # Hermes' venv is path-bound (cannot be copied): symlinked and shared by all trials
READY = threading.Event()
WARMUP_ERROR: str | None = None   # surfaced by /health so a broken template is visible, not silent


def make_hermes_home(home: Path):
    """Per-trial Hermes state: small dirs copied from the warm template, heavy dependency dirs shared."""
    stale = shutil.ignore_patterns("*.sock", "*.pid")   # runtime leftovers of the warm-up process (keep *.lock: uv needs them)
    for f in TEMPLATE.iterdir():
        dst = home / f.name
        if dst.exists() or stale(str(TEMPLATE), [f.name]):
            continue
        if f.name in SHARED:
            dst.symlink_to(f)
        elif f.is_dir():
            shutil.copytree(f, dst, symlinks=True, ignore=stale)
        else:
            shutil.copy2(f, dst)


def warmup(gateway_ok: threading.Event | None = None):
    """Once per worker boot: build the Hermes template and prime OpenCode's package cache."""
    try:
        time.sleep(3)  # let uvicorn start serving the gateway the harnesses will call
        meter.TOKENS["warmup"] = "warmup"
        if not (TEMPLATE / "installs").exists():
            TEMPLATE.mkdir(parents=True, exist_ok=True)
            w = Path(tempfile.mkdtemp())
            subprocess.run(["hermes", "chat", "--provider", "custom", "--base-url", BASE_URL, "--model", WARM_MODEL,
                            "-q", "Reply ok.", "--yolo", "--max-turns", "2", "--quiet"], cwd=w, timeout=600,
                           env={**os.environ, "HERMES_HOME": str(TEMPLATE), "OPENAI_API_KEY": "warmup", "OPENAI_BASE_URL": BASE_URL})
            for d in ("memories", "sessions"):   # the template must carry no state from the warm-up run
                shutil.rmtree(TEMPLATE / d, ignore_errors=True)
                (TEMPLATE / d).mkdir(exist_ok=True)
            for f in TEMPLATE.glob("state.db*"):
                f.unlink()
        w = Path(tempfile.mkdtemp())
        h = Path(tempfile.mkdtemp())
        OpenCode().run(Ctx("warmup", "Reply ok.", w, h, WARM_MODEL, 2, 180))
        for name, cmd in (("hermes", ["hermes", "--version"]), ("opencode", ["opencode", "--version"])):
            VERSIONS[name] = (subprocess.run(cmd, capture_output=True, text=True).stdout.strip().splitlines() or ["?"])[0]
        # trial users are unprivileged: dependencies read-only, shared caches writable
        subprocess.run(["chmod", "-R", "a+rX", str(TEMPLATE)], check=False)
        subprocess.run(["chmod", "-R", "a+rwX", str(TEMPLATE / "cache"), XDG_CACHE], check=False)
        # Hermes needs write access to its runtime (locks, generations), so installs/ must be writable by trial users.
        # Known trade-off (docs/limits.md): a hostile agent could tamper with the shared runtime.
        subprocess.run(["chmod", "-R", "a+rwX", str(TEMPLATE / "installs")], check=False)
    except Exception as e:  # noqa: BLE001 - a failed warm-up must not kill the worker
        global WARMUP_ERROR
        WARMUP_ERROR = f"{type(e).__name__}: {e}"
        print(f"[warmup] failed: {WARMUP_ERROR}", flush=True)
    finally:
        meter.TOKENS.pop("warmup", None)
        READY.set()


class Harness:
    name = ""
    capabilities: set = set()   # subset of {"skills", "memory"}

    def run(self, ctx: Ctx) -> Result:
        raise NotImplementedError

    def memory_saved(self, home: Path) -> bool:
        """After a memory-seed session: did the fact actually get persisted? (Harnesses without memory: always True.)"""
        return True


class Hermes(Harness):
    name = "hermes"
    capabilities = {"skills", "memory"}

    def memory_saved(self, home: Path) -> bool:
        from graders import read_text   # symlink-safe: the memory dir is agent-writable
        return any((read_text(home / "memories", f.name) or "").strip() for f in (home / "memories").glob("*.md"))

    def env(self, ctx):
        return {"HERMES_HOME": str(ctx.home), "OPENAI_API_KEY": ctx.key, "OPENAI_BASE_URL": BASE_URL}

    def run(self, ctx: Ctx) -> Result:
        make_hermes_home(ctx.home)
        install_skills(ctx.skills, ctx.home / "skills", ctx.home)
        chown_tree(ctx.home, ctx.uid)
        chown_tree(ctx.workdir, ctx.uid)
        # Hermes reads memory implicitly (injected into the system prompt), so no tool call shows it: record what the
        # session starts with, so memory READS are visible in the trace like memory writes are.
        from graders import read_text   # symlink-safe: the memory dir is agent-writable
        mem = [(f.name, t) for f in sorted((ctx.home / "memories").glob("*.md")) if (t := read_text(ctx.home / "memories", f.name)) and t.strip()]
        pre = ([{"type": "tool_call", "id": "memory-context", "name": "memory_context", "kind": "memory", "input": {"files": [n for n, _ in mem]}},
                {"type": "tool_result", "id": "memory-context", "name": "memory_context", "error": False,
                 "output": "\n---\n".join(f"{n}:\n{t.strip()}" for n, t in mem)}] if mem else [])
        cmd = ["hermes", "chat", "--provider", "custom", "--base-url", BASE_URL, "--model", ctx.model,
               "-q", ctx.prompt, "--format", "stream-json", "--yolo", "--max-turns", str(ctx.max_turns)]
        lines, timed_out, code, err = _run(cmd, ctx, self.env(ctx))
        events, final, saw_result = list(pre), "", False
        for e in _json_lines(lines):
            t = e.get("type")
            if t == "text":  # Hermes streams token deltas: merge consecutive ones into one message
                if events and events[-1]["type"] == "assistant":
                    events[-1]["text"] += e.get("text", "")
                else:
                    events.append({"type": "assistant", "text": e.get("text", "")})
            elif t == "tool_use":
                events.append({"type": "tool_call", "id": e.get("tool_call_id"), "name": e.get("name", "?"), "input": e.get("input"),
                               "kind": _kind(e.get("name", ""))})
            elif t == "tool_result":
                events.append({"type": "tool_result", "id": e.get("tool_call_id"), "name": e.get("name", "?"),
                               "output": str(e.get("output"))[:4000], "error": bool(e.get("is_error"))})
            elif t == "result":
                saw_result = True
                final = e.get("text", "")
                if e.get("error"):
                    events.append({"type": "error", "message": str(e["error"])})
        return Result(events, final, timed_out, code, err, complete=saw_result)


class OpenCode(Harness):
    name = "opencode"
    capabilities = {"skills"}   # no built-in persistent memory

    def run(self, ctx: Ctx) -> Result:
        cfg = ctx.home / "opencode.json"
        cfg.write_text(json.dumps({
            "$schema": "https://opencode.ai/config.json", "autoupdate": False, "model": f"proxy/{ctx.model}",
            "provider": {"proxy": {"npm": "@ai-sdk/openai-compatible", "name": "proxy",
                                   "options": {"baseURL": BASE_URL, "apiKey": "{env:EVAL_TRIAL_ID}"},
                                   "models": {ctx.model: {"name": ctx.model, "tool_call": True}}}},
            "permission": {"edit": "allow", "bash": "allow", "webfetch": "deny", "external_directory": "deny"},
        }))
        install_skills(ctx.skills, ctx.workdir / ".opencode" / "skills", ctx.workdir)
        chown_tree(ctx.home, ctx.uid)
        chown_tree(ctx.workdir, ctx.uid)
        if not (ctx.workdir / ".git").exists():   # opencode treats the git root as the project root
            subprocess.run(["git", "init", "-q"], cwd=ctx.workdir, check=False,
                           **({"user": ctx.uid, "group": ctx.uid} if ctx.uid is not None else {}))
        env = {"OPENCODE_CONFIG": str(cfg), "EVAL_TRIAL_ID": ctx.key, "XDG_DATA_HOME": str(ctx.home / "data"),
               "XDG_CONFIG_HOME": str(ctx.home / "config"), "XDG_CACHE_HOME": XDG_CACHE}
        lines, timed_out, code, err = _run(["opencode", "run", ctx.prompt, "--format", "json"], ctx, env)
        events, texts, steps = [], [], 0
        for e in _json_lines(lines):
            part = e.get("part") if isinstance(e.get("part"), dict) else {}
            if e.get("type") == "text":
                texts.append(part.get("text", ""))
                events.append({"type": "assistant", "text": part.get("text", "")})
            elif e.get("type") == "step_finish":
                steps += 1
            elif e.get("type") == "tool_use":
                st = part.get("state") if isinstance(part.get("state"), dict) else {}
                name = part.get("tool", "")
                events.append({"type": "tool_call", "id": part.get("callID"), "name": name, "input": st.get("input"),
                               "kind": _kind(name)})
                events.append({"type": "tool_result", "id": part.get("callID"), "name": name,
                               "output": str(st.get("output", st.get("error", "")))[:4000],
                               "error": st.get("status") == "error"})
        # opencode has no --max-turns flag: enforce the step budget after the fact
        if steps > ctx.max_turns:
            events.append({"type": "error", "message": f"step_limit: {steps} > {ctx.max_turns}"})
        return Result(events, texts[-1] if texts else "", timed_out, code, err, complete=(code == 0 or bool(texts)))


HARNESSES = {h.name: h() for h in (Hermes, OpenCode)}
