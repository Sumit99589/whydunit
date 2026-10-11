"""Stage 7: validator, the Funnel detective (deterministic and LLM paths), case events and SSE."""

import json

import httpx
import pytest

from engine.api.app import create_app
from engine.runtime import events as ev
from engine.runtime.cache import DiskCache
from engine.runtime.llm import LLM
from engine.runtime.orchestrator import investigate, open_case, run_detectives
from engine.runtime.schemas import Finding, MetricRef
from engine.runtime.validator import Validator, extract_numbers


def test_number_extraction_ignores_dates_times_ids():
    nums = [
        n.text
        for n in extract_numbers(
            "Signup rate fell from 9.5% to 0.9% starting Thu Sep 24 09:00 UTC (2026-09-24) on iPhone 15; "
            "see ev_anal_123 and deploy 2bdecd6; budget $450 → $150; 1,234 visitors; z = -7.6"
        )
    ]
    assert nums == ["$450", "$150", "9.5%", "0.9%", "1,234", "-7.6"]


def test_validator_rules():
    metrics = {
        "m_a": MetricRef(id="m_a", name="rate before", value=0.0949, unit="rate"),
        "m_b": MetricRef(id="m_b", name="rate after", value=0.0009, unit="rate"),
        "m_c": MetricRef(id="m_c", name="drop", value=-0.402, unit="pct_change"),
    }
    v = Validator({"ev_1": object(), "ev_low": object()}, metrics, {"ev_1": 1.0, "ev_low": 0.6})
    ok = v.apply(
        Finding(
            claim="Fell 40% (9.5% → 0.1%)",
            evidence_ids=["ev_1"],
            metrics_refs=["m_a", "m_b", "m_c"],
            confidence=0.9,
        )
    )
    assert ok.status == "accepted" and ok.confidence == 0.9
    low = v.apply(
        Finding(claim="Fell 40%", evidence_ids=["ev_1", "ev_low"], metrics_refs=["m_c"], confidence=0.9)
    )
    assert low.confidence == pytest.approx(0.54)
    bad_num = v.apply(Finding(claim="Fell 55%", evidence_ids=["ev_1"], metrics_refs=["m_c"]))
    assert bad_num.status == "rejected" and "55%" in bad_num.rejection_reason
    no_ev = v.apply(Finding(claim="Something broke", evidence_ids=[], metrics_refs=[]))
    assert "cites no evidence" in no_ev.rejection_reason
    ghost = v.apply(Finding(claim="x", evidence_ids=["ev_nope"], metrics_refs=["m_zzz"]))
    assert "does not exist" in ghost.rejection_reason and "never computed" in ghost.rejection_reason


@pytest.fixture
async def no_llm(monkeypatch, pg):
    monkeypatch.setenv("NEBIUS_API_KEY", "")
    from engine.runtime import llm as llm_mod

    llm_mod.set_llm(None)
    yield pg
    llm_mod.set_llm(None)


async def test_funnel_detective_on_flagship(no_llm):
    pg = no_llm
    res = await investigate("fixture:3inc", detectives=["funnel"], with_lead=False)
    rep = res["reports"]["funnel"]
    assert rep.model_mode == "deterministic" and not rep.suspicions and len(rep.findings) >= 4
    claims = " ".join(f.claim for f in rep.findings)
    assert "real drop" in claims
    assert "Signup rate fell" in claims and "WebKit" in claims
    assert "Paid traffic" in claims
    assert "Brazil" in claims
    effects = {(h.effect.factor, json.dumps(h.effect.segment)) for h in rep.hypotheses}
    assert ("signup_rate", '{"engine": "webkit"}') in effects
    assert ("traffic", '{"channel": "paid"}') in effects
    assert ("payment_success_rate", '{"country": "BR"}') in effects
    assert all(h.effect.start is not None for h in rep.hypotheses)
    cid = res["case"].id
    types = [e["type"] for e in await ev.events_since(cid)]
    assert types[0] == "case_opened" and types[-1] == "investigation_complete"
    assert types.count("finding") == len(rep.findings) and "evidence_pinned" in types
    n_ev = (await pg.fetchrow("SELECT count(*) AS n FROM evidence WHERE case_id = %s", (cid,)))["n"]
    assert n_ev >= 5
    for f in rep.findings:
        assert set(f.evidence_ids) <= set(res["ctx"].evidence)


async def test_funnel_detective_noise_world(no_llm):
    res = await investigate("fixture:noise", detectives=["funnel"], with_lead=False)
    rep = res["reports"]["funnel"]
    assert rep.findings[0].claim.startswith("No real drop")
    assert not rep.hypotheses


class ScriptedBackend:
    """Nano asks for one extra breakdown; Super writes a report with one good and one bad finding,
    then fixes the bad one when re-prompted."""

    def __init__(self):
        self.calls = []

    async def complete(self, req):
        self.calls.append(req)
        model = req["model"]
        msgs = req["messages"]
        if "tools" in req:
            if any(m["role"] == "tool" for m in msgs):
                return _resp("DONE")
            return _resp(
                None,
                [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "segment_breakdown",
                            "arguments": json.dumps(
                                {
                                    "factor": "signup_rate",
                                    "dim": "device",
                                    "within_dim": "engine",
                                    "within_value": "webkit",
                                }
                            ),
                        },
                    }
                ],
            )
        text = msgs[-1]["content"]
        cat = _catalogue(text)
        if "rejected by the validator" in text:
            return _resp(
                json.dumps(
                    {
                        "claim": "Signup rate in WebKit collapsed.",
                        "kind": "observed",
                        "evidence_ids": [cat["ev"]],
                        "metrics_refs": [],
                        "confidence": 0.8,
                    }
                )
            )
        return _resp(
            json.dumps(
                {
                    "summary": "WebKit signups broke.",
                    "findings": [
                        {
                            "claim": "Signups collapsed in WebKit.",
                            "kind": "observed",
                            "evidence_ids": [cat["ev"]],
                            "metrics_refs": [],
                            "confidence": 0.9,
                        },
                        {
                            "claim": "Signup rate fell 99% in WebKit.",
                            "kind": "observed",
                            "evidence_ids": [cat["ev"]],
                            "metrics_refs": [],
                            "confidence": 0.9,
                        },
                    ],
                }
            )
        )
        del model


def _catalogue(text):
    import re

    return {"ev": re.search(r"(ev_anal_[0-9a-f]+)", text).group(1)}


def _resp(content, tool_calls=None):
    return {
        "choices": [{"message": {"content": content, "tool_calls": tool_calls}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


async def test_llm_path_with_scripted_backend(pg, tmp_path):
    backend = ScriptedBackend()
    llm = LLM(backend=backend, cache=DiskCache(directory=tmp_path, enabled=False))
    case, reg = await open_case("fixture:3inc")
    ctx, reports = await run_detectives(case, reg, ["funnel"], llm=llm)
    rep = reports["funnel"]
    assert rep.model_mode == "llm"
    assert [f.claim for f in rep.findings] == [
        "Signups collapsed in WebKit.",
        "Signup rate in WebKit collapsed.",
    ]
    assert rep.cost_usd > 0
    roles = [c["model"] for c in backend.calls]
    assert roles[0] == ctx.llm.model_id("nano") and ctx.llm.model_id("super") in roles
    types = [e["type"] for e in await ev.events_since(case.id)]
    assert "tool_call" in types and types.count("finding") == 2
    row = await pg.fetchrow(
        "SELECT count(*) AS n, sum(cost_usd) AS c FROM llm_calls WHERE case_id = %s", (case.id,)
    )
    assert row["n"] >= 3 and row["c"] > 0


async def test_api_case_and_sse_replay(no_llm):
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60
    ) as c:
        res = await investigate("fixture:3inc", detectives=["funnel"], with_lead=False)
        cid = res["case"].id
        body = (await c.get(f"/cases/{cid}")).json()
        assert body["case"]["id"] == cid and len(body["findings"]) >= 4
        async with c.stream("GET", f"/cases/{cid}/stream", params={"replay": True, "speed": 1000}) as r:
            text = ""
            async for chunk in r.aiter_text():
                text += chunk
                if "event: end" in text:
                    break
        assert (
            "event: case_opened" in text
            and "event: finding" in text
            and "event: investigation_complete" in text
        )
        listed = (await c.get("/cases")).json()
        assert any(x["id"] == cid for x in listed)
