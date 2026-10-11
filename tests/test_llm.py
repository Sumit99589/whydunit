import json

import pytest

from engine.runtime.cache import DiskCache
from engine.runtime.llm import LLM, BudgetExceeded, CostMeter, LLMUnavailable, extract_json


class FakeBackend:
    def __init__(self, reply=None):
        self.requests = []
        self.reply = reply

    async def complete(self, request):
        self.requests.append(request)
        if self.reply:
            return self.reply(request)
        return {
            "choices": [{"message": {"content": f"echo {request['model']}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }


@pytest.fixture
def cache(tmp_path):
    return DiskCache(directory=tmp_path, enabled=True)


async def test_role_selection_and_cost(cache):
    be = FakeBackend()
    llm = LLM(backend=be, cache=cache)
    meter = CostMeter(case_id="c1")
    r = await llm.chat("nano", [{"role": "user", "content": "hi"}], meter=meter)
    cfg = llm.cfg["roles"]["nano"]
    assert be.requests[0]["model"] == cfg["id"]
    assert r.cost_usd == pytest.approx((1000 * cfg["price_in"] + 500 * cfg["price_out"]) / 1e6)
    assert meter.calls[0].case_id == "c1"


async def test_cache_hit_is_free_and_skips_backend(cache):
    be = FakeBackend()
    llm = LLM(backend=be, cache=cache)
    meter = CostMeter()
    await llm.chat("super", [{"role": "user", "content": "x"}], meter=meter)
    r2 = await llm.chat("super", [{"role": "user", "content": "x"}], meter=meter)
    assert len(be.requests) == 1
    assert r2.cached and meter.calls[1].cost_usd == 0


async def test_reasoning_switch(cache):
    be = FakeBackend()
    llm = LLM(backend=be, cache=cache)
    await llm.chat("ultra", [{"role": "user", "content": "a"}])
    await llm.chat("nano", [{"role": "user", "content": "b"}])
    assert be.requests[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert be.requests[1]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


async def test_system_flag_reasoning(cache):
    be = FakeBackend()
    cfg = json.loads(json.dumps(LLM(backend=be, cache=cache).cfg))
    cfg["reasoning_switch"] = "system_flag"
    llm = LLM(backend=be, cache=cache, config=cfg)
    await llm.chat("nano", [{"role": "system", "content": "be terse"}, {"role": "user", "content": "q"}])
    assert be.requests[0]["messages"][0]["content"].startswith("/no_think")


async def test_tool_call_parsing(cache):
    def reply(req):
        return {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "t1",
                                "type": "function",
                                "function": {"name": "get_metric", "arguments": '{"metric": "paid_subs"}'},
                            }
                        ],
                    }
                }
            ],
            "usage": {},
        }

    llm = LLM(backend=FakeBackend(reply), cache=cache)
    r = await llm.chat("nano", [{"role": "user", "content": "q"}], tools=[{"type": "function"}])
    assert r.tool_calls[0].name == "get_metric"
    assert r.tool_calls[0].arguments == {"metric": "paid_subs"}


async def test_fallback_ultra_to_super(cache):
    be = FakeBackend()
    llm = LLM(backend=be, cache=cache)
    llm.disable_role("ultra")
    r = await llm.chat("ultra", [{"role": "user", "content": "q"}])
    assert r.role == "super"
    llm.disable_role("omni")
    with pytest.raises(LLMUnavailable):
        llm.resolve_role("omni")


async def test_budget(cache):
    llm = LLM(backend=FakeBackend(), cache=cache)
    meter = CostMeter(max_cost_usd=0.0000001)
    await llm.chat("ultra", [{"role": "user", "content": "q"}], meter=meter)
    with pytest.raises(BudgetExceeded):
        await llm.chat("ultra", [{"role": "user", "content": "q2"}], meter=meter)


def test_extract_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"a": [1,2]} done') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        extract_json("nothing here")
