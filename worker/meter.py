"""Model gateway: forwards OpenAI-style chat requests to Azure and meters usage per trial.

Harnesses talk to this as a plain OpenAI-compatible endpoint, using the trial id as the API key,
so token/latency capture is identical no matter which harness is running.
"""
import json
import os
import secrets
import time
from collections import defaultdict
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()
UNSUPPORTED_PARAMS = ("reasoning_effort",)
OVERRIDES: dict = {}  # trial_id -> request params forced by the platform (e.g. temperature)
MODELS = yaml.safe_load(Path(os.environ.get("MODELS_FILE", "/config/models.yaml")).read_text())
USAGE = defaultdict(lambda: {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "steps": 0, "latency_ms": 0, "errors": 0})
BUDGETS: dict = {}     # trial_id -> {"max_steps": int, "max_tokens": int}; enforced here so every harness is limited identically
EXHAUSTED: dict = {}   # trial_id -> "steps" | "tokens" (which budget stopped the trial)
RESOLVED: dict = {}    # trial_id -> model snapshot id reported by Azure (e.g. gpt-4.1-mini-2025-04-14)
TOKENS: dict = {}      # bearer secret -> trial_id. The gateway only serves secrets issued here, so an agent cannot
                       # call Azure unmetered, spend another trial's budget, or grow server state with made-up ids.
BASE: dict = {}        # trial_id -> (steps, tokens) already used when the budget window started (see reset_budget)


def register(trial_id: str) -> str:
    """Issue the unguessable bearer secret a trial's harness uses as its API key."""
    secret = secrets.token_urlsafe(24)
    TOKENS[secret] = trial_id
    return secret


def release(trial_id: str):
    """Forget everything the gateway holds for a trial (safe to call twice)."""
    for k in [k for k, v in TOKENS.items() if v == trial_id]:
        TOKENS.pop(k, None)
    for d in (USAGE, BUDGETS, EXHAUSTED, RESOLVED, OVERRIDES, BASE):
        d.pop(trial_id, None)


def reset_budget(trial_id: str):
    """Start a fresh budget window (used after the memory-seed phase so memory-ON and memory-OFF get equal budgets).
    Usage/cost keep accumulating; only the limit check restarts."""
    u = USAGE[trial_id]
    BASE[trial_id] = (u["steps"], u["prompt_tokens"] + u["completion_tokens"])
    EXHAUSTED.pop(trial_id, None)


def usage_for(trial_id: str) -> dict:
    return dict(USAGE[trial_id]) if trial_id in USAGE else dict(USAGE.default_factory())


def cost_usd(model: str, u: dict) -> float:
    p = MODELS[model]["price_per_1m"]
    return (u["prompt_tokens"] * p["input"] + u["completion_tokens"] * p["output"]) / 1e6


def azure_url(model: str) -> str:
    if model not in MODELS:
        raise HTTPException(400, f"unknown model {model}")
    dep = os.environ[MODELS[model]["deployment_env"]]
    base = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    return f"{base}/openai/deployments/{dep}/chat/completions?api-version={os.environ['AZURE_OPENAI_API_VERSION']}"


def _record(trial_id, usage, started, error=False, model=None):
    u = USAGE[trial_id]
    if model:
        RESOLVED[trial_id] = model
    u["calls"] += 1
    u["latency_ms"] += int((time.time() - started) * 1000)
    u["errors"] += int(error)
    if usage:
        u["prompt_tokens"] += usage.get("prompt_tokens", 0)
        u["completion_tokens"] += usage.get("completion_tokens", 0)


async def call_azure(model: str, body: dict, trial_id: str = "judge") -> dict:
    """Non-streaming call used by the LLM judge (also metered)."""
    started = time.time()
    body = {**body, "stream": False}
    body.pop("model", None)
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(azure_url(model), json=body, headers={"api-key": os.environ["AZURE_OPENAI_API_KEY"]})
    data = r.json() if r.status_code == 200 else {}
    _record(trial_id, data.get("usage"), started, error=r.status_code != 200)
    r.raise_for_status()
    return data


@router.post("/v1/chat/completions")
async def chat(req: Request):
    token = (req.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    trial_id = TOKENS.get(token)
    if trial_id is None:   # unknown / missing secret: never forward, never create state
        return JSONResponse({"error": {"message": "unauthorized: unknown gateway token", "code": "unauthorized"}}, status_code=401)
    body = await req.json()
    model = body.get("model", "")
    model = model.split("/")[-1]  # tolerate "provider/model" ids
    url = azure_url(model)
    body.pop("model", None)
    for k in UNSUPPORTED_PARAMS:  # harnesses send params non-reasoning Azure deployments reject
        body.pop(k, None)
    body.update(OVERRIDES.get(trial_id, {}))
    headers = {"api-key": os.environ["AZURE_OPENAI_API_KEY"], "Content-Type": "application/json"}
    started = time.time()

    b, u = BUDGETS.get(trial_id), USAGE[trial_id]
    if b:  # a "step" is an agent turn = a request that offers tools (excludes title/summary side calls)
        base_steps, base_tokens = BASE.get(trial_id, (0, 0))
        over = ("tokens" if u["prompt_tokens"] + u["completion_tokens"] - base_tokens >= b["max_tokens"]
                else "steps" if body.get("tools") and u["steps"] - base_steps >= b["max_steps"] else None)
        if over:
            EXHAUSTED[trial_id] = over
            return JSONResponse({"error": {"message": f"budget_exhausted: {over}", "code": "budget_exhausted"}}, status_code=400)
    is_step = bool(body.get("tools"))   # counted only once upstream accepts the call: Azure throttling must not eat the agent's turns

    if not body.get("stream"):
        try:
            async with httpx.AsyncClient(timeout=300) as c:
                r = await c.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:   # upstream hung / dropped: an error the harness can retry, counted as infra
            _record(trial_id, None, started, error=True)
            return JSONResponse({"error": {"message": f"upstream unavailable: {type(e).__name__}"}}, status_code=504)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        _record(trial_id, data.get("usage"), started, error=r.status_code != 200, model=data.get("model"))
        if r.status_code == 200 and is_step:
            u["steps"] += 1
        return JSONResponse(data or {"error": r.text}, status_code=r.status_code)

    body["stream_options"] = {"include_usage": True}

    client = httpx.AsyncClient(timeout=300)
    try:
        r = await client.send(client.build_request("POST", url, json=body, headers=headers), stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        _record(trial_id, None, started, error=True)
        return JSONResponse({"error": {"message": f"upstream unavailable: {type(e).__name__}"}}, status_code=504)
    if r.status_code != 200:  # surface upstream errors (429, 400...) with their real status
        err = await r.aread()
        await client.aclose()
        _record(trial_id, None, started, error=True)
        print(f"[proxy] upstream {r.status_code}: {err[:500]!r}", flush=True)
        return JSONResponse(json.loads(err) if err[:1] == b"{" else {"error": err.decode()}, status_code=r.status_code,
                            headers={k: v for k, v in r.headers.items() if k.lower() == "retry-after"})

    if is_step:
        u["steps"] += 1

    async def gen():
        usage, resolved = None, None
        try:
            async for line in r.aiter_lines():
                if line.startswith("data: ") and line[6:].strip() not in ("", "[DONE]"):
                    try:
                        chunk = json.loads(line[6:])
                        usage = chunk.get("usage") or usage
                        resolved = chunk.get("model") or resolved
                    except ValueError:
                        pass
                yield line + "\n"
        finally:
            await r.aclose()
            await client.aclose()
            # client went away before Azure's final usage chunk: Azure still bills the prompt, so estimate it (~4 chars/token)
            # instead of undercounting cost and budget
            est = None if usage else {"prompt_tokens": len(json.dumps(body)) // 4, "completion_tokens": 0}
            _record(trial_id, usage or est, started, error=est is not None, model=resolved)

    return StreamingResponse(gen(), media_type="text/event-stream")
