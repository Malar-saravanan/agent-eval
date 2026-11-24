import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import meter

REAL_CLIENT = httpx.AsyncClient
app = FastAPI()
app.include_router(meter.router)
client = TestClient(app)

OK = {"model": "gpt-4.1-mini-2025-04-14", "choices": [{"message": {"role": "assistant", "content": "hi"}}],
      "usage": {"prompt_tokens": 40, "completion_tokens": 10}}


class Upstream:
    """Fake Azure: records every forwarded request, answers from a queue (last reply repeats)."""

    def __init__(self):
        self.requests, self.replies = [], [lambda req: httpx.Response(200, json=OK)]

    def handler(self, request: httpx.Request):
        self.requests.append(request)
        i = min(len(self.requests) - 1, len(self.replies) - 1)
        return self.replies[i](request)

    @property
    def bodies(self):
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture
def upstream(monkeypatch):
    up = Upstream()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(up.handler), **kw))
    return up


def post(trial_id="t1", token=None, **body):
    """POST as a registered trial. The gateway only serves secrets issued by meter.register (here token == trial id)."""
    body.setdefault("model", "gpt-4.1-mini")
    body.setdefault("messages", [{"role": "user", "content": "hi"}])
    if token is None:
        meter.TOKENS.setdefault(trial_id, trial_id)
        token = trial_id
    return client.post("/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {token}"})


TOOLS = [{"type": "function", "function": {"name": "f", "parameters": {}}}]


def test_non_stream_success_records_usage_and_resolved_model(upstream):
    r = post()
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "hi"
    u = meter.usage_for("t1")
    assert (u["calls"], u["prompt_tokens"], u["completion_tokens"], u["errors"]) == (1, 40, 10, 0)
    assert meter.RESOLVED["t1"] == "gpt-4.1-mini-2025-04-14"


def test_forwards_to_azure_deployment_url_with_key_and_without_model(upstream):
    post()
    req = upstream.requests[0]
    assert str(req.url) == "https://azure.invalid/openai/deployments/dep-mini/chat/completions?api-version=2024-01-01"
    assert req.headers["api-key"] == "test-key"
    assert "model" not in upstream.bodies[0]


def test_trial_id_is_the_bearer_token_and_usage_is_per_trial(upstream):
    post("a"), post("a"), post("b")
    assert meter.usage_for("a")["calls"] == 2 and meter.usage_for("b")["calls"] == 1


def test_upstream_429_is_passed_through_and_counted_as_error(upstream):
    upstream.replies = [lambda req: httpx.Response(429, json={"error": {"message": "slow down"}})]
    r = post()
    assert r.status_code == 429 and r.json()["error"]["message"] == "slow down"
    u = meter.usage_for("t1")
    assert u["errors"] == 1 and u["calls"] == 1 and u["prompt_tokens"] == 0


def test_upstream_non_json_error_body_is_wrapped(upstream):
    upstream.replies = [lambda req: httpx.Response(502, text="bad gateway", headers={"content-type": "text/plain"})]
    r = post()
    assert r.status_code == 502 and r.json() == {"error": "bad gateway"}
    assert meter.usage_for("t1")["errors"] == 1


def test_reasoning_effort_is_stripped_other_params_kept(upstream):
    post(reasoning_effort="high", max_tokens=7)
    sent = upstream.bodies[0]
    assert "reasoning_effort" not in sent and sent["max_tokens"] == 7


def test_provider_prefixed_model_name_is_tolerated(upstream):
    assert post(model="proxy/gpt-4.1-mini").status_code == 200


def test_unknown_model_is_400(upstream):
    r = post(model="nope")
    assert r.status_code == 400 and not upstream.requests


def test_per_trial_temperature_override_beats_client_value(upstream):
    meter.OVERRIDES["t1"] = {"temperature": 0.0}
    post(temperature=1.0)
    post("other", temperature=1.0)
    assert upstream.bodies[0]["temperature"] == 0.0
    assert upstream.bodies[1]["temperature"] == 1.0   # other trials are unaffected


def test_step_budget_counts_only_requests_with_tools(upstream):
    meter.BUDGETS["t1"] = {"max_steps": 2, "max_tokens": 100_000}
    assert post(tools=TOOLS).status_code == 200
    assert post().status_code == 200                   # no tools: side call, not a step
    assert post().status_code == 200
    assert meter.USAGE["t1"]["steps"] == 1
    assert post(tools=TOOLS).status_code == 200        # step 2
    r = post(tools=TOOLS)                              # step 3 -> refused
    assert r.status_code == 400 and r.json()["error"]["code"] == "budget_exhausted"
    assert meter.EXHAUSTED["t1"] == "steps"
    assert len(upstream.requests) == 4                 # the refused call never reached Azure
    assert post().status_code == 200                   # tool-less calls still allowed after steps are used up


def test_token_budget_exceeded(upstream):
    big = {**OK, "usage": {"prompt_tokens": 60_000, "completion_tokens": 0}}
    upstream.replies = [lambda req: httpx.Response(200, json=big)]
    meter.BUDGETS["t1"] = {"max_steps": 50, "max_tokens": 100_000}
    assert post(tools=TOOLS).status_code == 200
    assert post(tools=TOOLS).status_code == 200        # 60k < 100k at check time
    r = post(tools=TOOLS)                              # 120k >= 100k
    assert r.status_code == 400 and "tokens" in r.json()["error"]["message"]
    assert meter.EXHAUSTED["t1"] == "tokens"


def test_token_budget_applies_even_without_tools(upstream):
    meter.BUDGETS["t1"] = {"max_steps": 50, "max_tokens": 50}
    assert post().status_code == 200                   # 0 used
    assert post().status_code == 400 and meter.EXHAUSTED["t1"] == "tokens"


def test_no_budget_means_no_limit(upstream):
    for _ in range(5):
        assert post(tools=TOOLS).status_code == 200
    assert "t1" not in meter.EXHAUSTED


def sse(*chunks):
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def test_stream_success_relays_and_records_usage(upstream):
    upstream.replies = [lambda req: httpx.Response(200, content=sse(
        {"model": "gpt-4.1-mini-2025-04-14", "choices": [{"delta": {"content": "h"}}]},
        {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}), headers={"content-type": "text/event-stream"})]
    r = post(stream=True)
    assert r.status_code == 200 and "data: [DONE]" in r.text and '"content": "h"' in r.text
    assert upstream.bodies[0]["stream_options"] == {"include_usage": True}
    u = meter.usage_for("t1")
    assert (u["calls"], u["prompt_tokens"], u["completion_tokens"], u["errors"]) == (1, 7, 3, 0)
    assert meter.RESOLVED["t1"] == "gpt-4.1-mini-2025-04-14"


def test_stream_upstream_429_keeps_status_and_retry_after(upstream):
    upstream.replies = [lambda req: httpx.Response(429, json={"error": {"message": "rl"}}, headers={"retry-after": "3"})]
    r = post(stream=True)
    assert r.status_code == 429 and r.headers["retry-after"] == "3"
    assert meter.usage_for("t1")["errors"] == 1


def test_cost_usd_uses_model_prices():
    u = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert meter.cost_usd("gpt-4.1-mini", u) == pytest.approx(0.40 + 1.60)


def test_call_azure_records_usage_and_raises_on_error(upstream):
    import asyncio
    data = asyncio.run(meter.call_azure("gpt-4.1-mini", {"messages": [], "stream": True}, trial_id="judge"))
    assert data["usage"]["prompt_tokens"] == 40 and upstream.bodies[0]["stream"] is False
    upstream.replies = [lambda req: httpx.Response(500, json={})]
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(meter.call_azure("gpt-4.1-mini", {"messages": []}, trial_id="judge"))
    assert meter.usage_for("judge")["errors"] == 1



# --- review regressions: authentication and accounting -------------------------------------------------------
def test_unknown_missing_or_forged_tokens_get_401_and_create_no_state(upstream):
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Bearer "}):
        r = client.post("/v1/chat/completions", json={"model": "gpt-4.1-mini", "messages": []}, headers=headers)
        assert r.status_code == 401
    assert upstream.requests == []                                                  # nothing reached Azure
    assert len(meter.USAGE) == 0                                                    # and no per-token state was allocated


def test_one_trial_cannot_use_anothers_budget_or_usage(upstream):
    meter.TOKENS["secret-a"], meter.TOKENS["secret-b"] = "A", "B"
    post(token="secret-a")
    post(token="secret-a")
    assert meter.usage_for("A")["calls"] == 2 and meter.usage_for("B")["calls"] == 0


def test_throttled_calls_do_not_consume_the_agents_steps(upstream):
    meter.BUDGETS["t1"] = {"max_steps": 1, "max_tokens": 10**9}
    upstream.replies = [lambda req: httpx.Response(429, json={"error": {"message": "slow"}}),
                        lambda req: httpx.Response(200, json=OK)]
    assert post(tools=TOOLS).status_code == 429          # Azure throttled: this must NOT use up the single step
    assert post(tools=TOOLS).status_code == 200          # the agent still has its step
    assert post(tools=TOOLS).status_code == 400          # now it is spent


def test_upstream_hang_becomes_a_counted_504_not_an_exception(monkeypatch):
    def boom(**kw):
        def handler(request):
            raise httpx.ReadTimeout("hung", request=request)
        return REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)
    monkeypatch.setattr(httpx, "AsyncClient", boom)
    r = post()
    assert r.status_code == 504
    assert meter.usage_for("t1")["errors"] == 1


def test_budget_window_can_be_restarted_after_the_seed_phase(upstream):
    meter.BUDGETS["t1"] = {"max_steps": 2, "max_tokens": 10**9}
    post(tools=TOOLS); post(tools=TOOLS)
    assert post(tools=TOOLS).status_code == 400            # spent in the seed phase
    meter.reset_budget("t1")                               # task phase starts with a full budget
    assert post(tools=TOOLS).status_code == 200
    assert meter.usage_for("t1")["steps"] == 3             # cost/usage keep accumulating across phases
