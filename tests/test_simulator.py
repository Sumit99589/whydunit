from datetime import UTC, datetime, timedelta

import pytest

from simulator import state
from simulator.schedule import load_schedule, parse_offset
from simulator.tick import payment_declines_active, tick


def test_parse_offset():
    assert parse_offset("4d") == timedelta(days=4)
    assert parse_offset("4d12h") == timedelta(days=4, hours=12)
    assert parse_offset("90m") == timedelta(minutes=90)
    with pytest.raises(ValueError):
        parse_offset("4 days")


def test_schedule_matches_plan():
    s = load_schedule()
    by_id = {i.id: i for i in s.incidents}
    assert by_id["safari_signup_bug"].at == timedelta(days=4)
    assert by_id["ads_budget_cap"].at == timedelta(days=4, hours=12)
    assert by_id["payment_declines"].at == timedelta(days=5)
    assert by_id["payment_declines"].action["country"] == "BR"


def test_payment_declines_window_and_mitigation():
    s = load_schedule()
    start = datetime(2026, 10, 1, tzinfo=UTC)
    fired = {"payment_declines": {"at": "x"}}
    assert payment_declines_active(s, start, fired, {}, start + timedelta(days=4)) == {}
    assert payment_declines_active(s, start, fired, {}, start + timedelta(days=6)) == {"BR": 0.18}
    assert payment_declines_active(s, start, fired, {}, start + timedelta(days=10)) == {}
    assert (
        payment_declines_active(s, start, fired, {"payment_declines": "y"}, start + timedelta(days=6)) == {}
    )


@pytest.fixture
async def sim_db(pg, monkeypatch):
    monkeypatch.setenv("WHYDUNIT_INGEST_KEY", "wd_test_sim")
    monkeypatch.delenv("WHYDUNIT_ENGINE_URL", raising=False)
    monkeypatch.delenv("ACME_URL", raising=False)
    monkeypatch.setenv("NEBIUS_API_KEY", "")
    await pg.execute("TRUNCATE sim.state, sim.ticks, sim.health")
    await pg.execute("TRUNCATE mock_ads.hourly_stats, mock_ads.change_events, mock_ads.campaigns CASCADE")
    yield pg


async def test_offline_ticks_fire_incidents_and_write_data(sim_db, monkeypatch):
    pg = sim_db
    t0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    await state.put("start", t0.isoformat())
    await state.put("last_tick_end", (t0 + timedelta(days=4, hours=11)).isoformat())
    # A tick spanning T+4d12h fires the ads incident (the deploy bug needs a GitHub token, so it errors and retries).
    s = await tick(t0 + timedelta(days=4, hours=12, minutes=30), skip_browsers=True)
    assert "ads_budget_cap" in s["fired"]
    assert "safari_signup_bug" in s["incident_errors"]
    assert s["visitors"] > 50 and s["events"] > 50
    ev = await pg.fetchrow("SELECT user_email FROM mock_ads.change_events ORDER BY id DESC LIMIT 1")
    assert ev["user_email"] == "jordan@acme-notes.test"
    gt = s["ground_truth"]
    fired = {i["id"]: i["fired_at"] for i in gt["incidents"]}
    assert fired["ads_budget_cap"] and fired["safari_signup_bug"] is None
    # Next tick: WebKit health is down, so webkit visitors are blocked from signing up.
    await pg.execute(
        "INSERT INTO sim.health (probe, ok) VALUES ('webkit-mobile', false), ('webkit-desktop', false)"
    )
    s2 = await tick(t0 + timedelta(days=4, hours=15), skip_browsers=True)
    assert s2["signup_blocked"] > 0
    rows = await pg.fetch(
        "SELECT browser, os, count(*) AS n FROM events WHERE name = 'signup_completed' AND ts >= %s "
        "GROUP BY 1, 2",
        (t0 + timedelta(days=4, hours=12, minutes=30),),
    )
    assert all(not (r["os"] in ("iOS", "iPadOS") or r["browser"] == "Safari") for r in rows)
    assert (await pg.fetchrow("SELECT count(*) AS n FROM sim.ticks WHERE ok"))["n"] == 2
