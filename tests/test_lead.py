"""Stage 9 "done when": the flagship verdict names all three causes within ±5 pp of ground truth with no false
accusations; noise gives "no real drop"; a tracking bug gives a measurement verdict; a holiday red herring
doesn't get the harmless deploy accused."""

import pytest

from engine.fixtures.world import load_meta, resolve_world
from engine.runtime.orchestrator import investigate


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "")
    from engine.runtime import llm as llm_mod

    llm_mod.set_llm(None)
    yield
    llm_mod.set_llm(None)


TRUTH_KEY = {
    ("signup_rate", "engine"): "deploy_bug",
    ("traffic", "channel"): "ads_budget_cap",
    ("payment_success_rate", "country"): "payment_declines",
    ("traffic", "country"): "public_holiday",
}


def truth_shares(world):
    meta = load_meta(resolve_world(world))
    return {
        i["id"].split(":")[0]: v["share"]
        for i in meta["incidents"]
        for k, v in (meta["truth"] or {}).get("incidents", {}).items()
        if k == i["id"]
    }


async def test_flagship_verdict(pg):
    v = (await investigate("fixture:3inc"))["verdict"]
    assert v["kind"] == "causes"
    truth = truth_shares("fixture:3inc")
    got = {}
    for c in v["causes"]:
        key = TRUTH_KEY[(c["factor"], next(iter(c["segment"])))]
        got[key] = c["share_of_explained"]
    assert set(got) == set(truth) == {"deploy_bug", "ads_budget_cap", "payment_declines"}
    for k in truth:
        assert abs(got[k] - truth[k]) <= 0.05, (k, got[k], truth[k])
    assert [a["type"] for a in v["actions"]] == ["code_pr", "config", "recommendation"]
    assert not v["rejected"]
    assert "Three causes explain it" in v["narrative"]
    kinds = {(t["to"], t["kind"]) for t in v["thread"]}
    assert ("world", "external_release") in kinds and ("funnel", "before_after") in kinds
    assert all(t["verdict"] == "supports" for t in v["thread"])


async def test_noise_gives_no_real_drop(pg):
    v = (await investigate("fixture:noise"))["verdict"]
    assert v["kind"] == "no_real_drop" and not v["causes"]
    assert v["narrative"].startswith("No real drop")


async def test_seasonal_dip_gives_no_real_drop(pg):
    v = (await investigate("fixture:seasonality"))["verdict"]
    assert v["kind"] == "no_real_drop" and "usual pattern" in v["narrative"]


async def test_tracking_bug_gives_measurement_verdict(pg):
    v = (await investigate("fixture:tracking", metric="signups"))["verdict"]
    assert v["kind"] == "measurement"
    assert v["narrative"].startswith("Measurement problem, not a business drop.")
    assert v["actions"][0]["title"].startswith("Fix the analytics event")


async def test_holiday_red_herring_no_false_accusation(pg):
    v = (await investigate("fixture:holiday_red_herring"))["verdict"]
    assert v["kind"] == "causes"
    assert [c["segment"] for c in v["causes"]] == [{"country": "DE"}]
    assert not any(c["factor"] == "signup_rate" for c in v["causes"])
    assert not any(a["type"] == "code_pr" for a in v["actions"])
