import asyncio
import hmac
import json
import os
import secrets
import threading
import traceback
from pathlib import Path

import harnesses
import meter
import trial
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

app = FastAPI(title="evals-worker")
app.include_router(meter.router)

# /trial can start paid runs and wipes directories, and agents share this container's network namespace, so it is
# protected by a secret that only the API can read: the worker writes it to a root-only file on a volume shared with the
# API container; agents run as unprivileged users with a scrubbed environment and cannot read it.
TOKEN_FILE = Path(os.environ.get("WORKER_TOKEN_FILE", "/ipc/worker-token"))
WORKER_TOKEN = secrets.token_urlsafe(32)
HEARTBEAT_S = 15   # a trial can run for many minutes; Node's fetch gives up waiting for response headers after 300s


def publish_token():
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(TOKEN_FILE.parent, 0o700)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(WORKER_TOKEN)


@app.on_event("startup")
def _warm():
    try:
        publish_token()
    except OSError as e:   # no shared volume (e.g. local dev): /trial stays locked, tests inject the token directly
        print(f"[worker] could not publish token to {TOKEN_FILE}: {e}", flush=True)
    trial.sync_tasks()
    threading.Thread(target=harnesses.warmup, daemon=True).start()


@app.get("/health")
def health():
    return {"ok": True, "ready": harnesses.READY.is_set(), "warmup_error": harnesses.WARMUP_ERROR}


async def _safe_run(req: dict) -> dict:
    try:
        return await trial.run_trial(req)
    except Exception as e:  # noqa: BLE001 - surface worker bugs in the trial record instead of a bare 500
        traceback.print_exc()
        return {"trial_id": req.get("trial_id"), "task_id": req.get("task_id"), "status": "infra_error", "score": None,
                "reasoning": f"worker error: {type(e).__name__}: {e}", "events": [], "usage": {}, "cost_usd": 0}


@app.post("/trial")
async def run(req: dict, x_worker_token: str | None = Header(default=None)):
    """req: {trial_id, task_id, config: {harness, model, settings: {skills, memory, temperature, max_turns, token_budget, nudge}}}

    The response is a JSON document preceded by whitespace heartbeats while the trial runs (valid JSON, and it keeps the
    HTTP connection alive for as long as a trial needs). Auth and id validation happen before streaming starts."""
    if not hmac.compare_digest((x_worker_token or "").encode(), WORKER_TOKEN.encode()):
        raise HTTPException(401, "invalid or missing worker token")
    if not (trial.ID_RE.match(str(req.get("trial_id", ""))) and trial.ID_RE.match(str(req.get("task_id", "")))):
        raise HTTPException(400, "trial_id and task_id must match [A-Za-z0-9_-]{1,64}")

    async def body():
        job = asyncio.create_task(_safe_run(req))      # keeps running (and cleaning up) even if the client disconnects
        while True:
            done, _ = await asyncio.wait({job}, timeout=HEARTBEAT_S)
            if done:
                break
            yield b" "
        yield json.dumps(job.result()).encode()

    return StreamingResponse(body(), media_type="application/json")
