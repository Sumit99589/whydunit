"""Stage 8: every detective returns a valid report on fixture worlds, and says the right thing."""

import pytest

from engine.runtime.orchestrator import investigate


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "")
    from engine.runtime import llm as llm_mod

    llm_mod.set_llm(None)
    yield
    llm_mod.set_llm(None)


def claims(rep):
    return " ".join(f.claim for f in rep.findings)


async def test_flagship_team(pg):
    res = await investigate("fixture:3inc", with_lead=False)
    r = res["reports"]
    assert set(r) == {"funnel", "deploy", "session", "payments", "ads", "voice", "world"}
    for name, rep in r.items():
        assert rep.findings, name
        assert not rep.suspicions, (name, [s.rejection_reason for s in rep.suspicions])
    assert "refactor(signup)" in claims(r["deploy"]) and "requestIdleCallback" in claims(r["deploy"])
    assert "Safari on iPhone" in claims(r["deploy"]) and "passes on Chrome desktop" in claims(r["deploy"])
    assert "rage clicks" in claims(r["session"]) and "Create account" in claims(r["session"])
    assert "Brazil" in claims(r["payments"]) and "issuing banks" in claims(r["payments"])
    assert "$450 to $150" in claims(r["ads"]) and "limited by budget" in claims(r["ads"])
    assert "can't sign up" in claims(r["voice"])
    assert claims(r["world"]).startswith("No external cause found. Checked:")
    effects = {(h.proposed_by, h.effect.factor) for rep in r.values() for h in rep.hypotheses}
    assert {("deploy", "signup_rate"), ("ads", "traffic"), ("payments", "payment_success_rate")} <= effects


async def test_holiday_red_herring(pg):
    r = (await investigate("fixture:holiday_red_herring", detectives=["deploy", "world"], with_lead=False))[
        "reports"
    ]
    assert "Labour Day" in claims(r["world"])
    assert any(
        h.effect.factor == "traffic" and h.effect.segment == {"country": "US"} for h in r["world"].hypotheses
    )
    assert "passes on every browser" in claims(r["deploy"]) and not r["deploy"].hypotheses


async def test_outage(pg):
    r = (await investigate("fixture:outage", detectives=["payments", "world"], with_lead=False))["reports"]
    assert "API errors" in claims(r["payments"])
    assert "Stripe reported a major incident" in claims(r["world"])


async def test_competitor(pg):
    r = (await investigate("fixture:competitor", detectives=["world"], with_lead=False))["reports"]
    assert "Quillboard launches a free tier" in claims(r["world"])


async def test_tracking_bug_is_flagged(pg):
    r = (await investigate("fixture:tracking", metric="signups", detectives=["funnel"], with_lead=False))[
        "reports"
    ]
    assert "Tracking looks broken" in claims(r["funnel"])


async def test_quiet_world(pg):
    r = (
        await investigate(
            "fixture:noise", detectives=["funnel", "ads", "payments", "voice", "world"], with_lead=False
        )
    )["reports"]
    assert claims(r["funnel"]).startswith("No real drop")
    assert "looks normal" in claims(r["ads"]) and "look normal" in claims(r["payments"])
    assert "No unusual spike" in claims(r["voice"])
