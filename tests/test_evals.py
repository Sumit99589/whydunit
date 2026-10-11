"""Stage 13: the scorer, and one end-to-end scenario run."""

import pytest

from engine.evals.run import SCENARIOS, run_all, score


def test_score_rules():
    meta = {
        "incidents": [
            {
                "id": "deploy_bug:webkit",
                "causal": True,
                "affects": {"factor": "signup_rate", "segment": {"engine": "webkit"}},
            },
            {"id": "harmless_deploy", "causal": False, "affects": {}},
        ],
        "truth": {"incidents": {"deploy_bug:webkit": {"share": 1.0, "lost_paid_subs": 90}}},
    }
    sc = next(s for s in SCENARIOS if s.id == "S1")
    good = {
        "kind": "causes",
        "causes": [
            {
                "statement": "x",
                "factor": "signup_rate",
                "segment": {"engine": "webkit"},
                "share": 0.9,
                "share_of_explained": 1.0,
            }
        ],
    }
    r = score(sc, meta, good)
    assert r["top_cause_ok"] and not r["false_accusations"] and r["share_abs_errors_pp"] == [0.0]
    wrong = {
        "kind": "causes",
        "causes": [
            {
                "statement": "ads",
                "factor": "traffic",
                "segment": {"channel": "paid"},
                "share": 0.9,
                "share_of_explained": 1.0,
            }
        ],
    }
    r = score(sc, meta, wrong)
    assert (
        not r["top_cause_ok"] and r["false_accusations"] == ["ads"] and r["missed"] == ["deploy_bug:webkit"]
    )


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "")
    from engine.runtime import llm as llm_mod

    llm_mod.set_llm(None)
    yield
    llm_mod.set_llm(None)


async def test_red_herring_scenario_end_to_end(pg):
    out = await run_all(["S5"])
    r = out["scenarios"][0]
    assert r["top_cause_ok"] and not r["false_accusations"] and not r["missed"]
