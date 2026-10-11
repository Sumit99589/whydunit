from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest

from engine.api.app import create_app
from engine.mock_ads import store
from engine.mock_ads.model import DEFAULT_CAMPAIGNS, simulate


def test_budget_cap_reduces_afternoon_clicks():
    day = datetime(2026, 10, 6, tzinfo=UTC)
    generic = DEFAULT_CAMPAIGNS[1]
    full = simulate(
        generic,
        day,
        day + timedelta(days=1),
        spent_before=0,
        budget_at=lambda t: 400,
        rng=np.random.default_rng(3),
    )
    capped = simulate(
        generic,
        day,
        day + timedelta(days=1),
        spent_before=0,
        budget_at=lambda t: 150,
        rng=np.random.default_rng(3),
    )
    assert not any(h.budget_limited for h in full)
    first = next(h.hour.hour for h in capped if h.budget_limited)
    assert 9 <= first <= 15
    assert sum(h.cost for h in capped) <= 150
    # a cheap click can still fit in the leftover budget, but serving effectively stops
    assert sum(h.clicks for h in capped[first + 1 :]) <= 3


@pytest.fixture
async def ads(pg):
    await pg.execute("TRUNCATE mock_ads.hourly_stats, mock_ads.change_events, mock_ads.campaigns CASCADE")
    await store.seed_campaigns()
    await store.set_api_enabled(True)
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_budget_change_timeline_and_reports(ads):
    t0 = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=30)
    r = await ads.post(
        "/mock-ads/api/campaigns/1002/budget",
        json={"amount": 150, "user_email": "jordan@acme-notes.test", "client_type": "GOOGLE_ADS_WEB_CLIENT"},
    )
    assert r.status_code == 200 and r.json()["old"] == 400 and r.json()["new"] == 150
    tl = await store.budget_timeline("1002", t0)
    assert tl[0][1] == 400 and tl[-1][1] == 150
    fn = store.budget_fn(tl)
    assert fn(t0) == 400 and fn(datetime.now(UTC) + timedelta(seconds=5)) == 150

    hours = simulate(
        DEFAULT_CAMPAIGNS[1],
        t0,
        t0 + timedelta(hours=24),
        spent_before=0,
        budget_at=lambda t: 150,
        rng=np.random.default_rng(1),
    )
    await store.record_hours(hours)
    rep = (await ads.get("/mock-ads/api/reports/campaign_daily")).json()["results"]
    assert any(r["campaign.primary_status_reasons"] == ["BUDGET_CONSTRAINED"] for r in rep)
    ev = (await ads.get("/mock-ads/api/change_events")).json()["results"]
    assert ev[-1]["change_event.user_email"] == "jordan@acme-notes.test"
    page = await ads.get("/mock-ads/")
    assert page.status_code == 200 and "SIMULATED" in page.text and "Limited by budget" in page.text


async def test_no_api_mode(ads):
    await ads.post("/mock-ads/api/settings/api_access", json={"enabled": False})
    assert (await ads.get("/mock-ads/api/campaigns")).status_code == 503
    assert (await ads.get("/mock-ads/")).status_code == 200
    await ads.post("/mock-ads/api/settings/api_access", json={"enabled": True})
    assert (await ads.get("/mock-ads/api/campaigns")).status_code == 200
