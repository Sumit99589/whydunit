"""Stage 5: each connector returns uniform, tiered bundles; the registry walks the ladder."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from engine.connectors.acme_db import AcmePaymentLog, Helpdesk, Reviews
from engine.connectors.base import KIND_SCHEMAS, KINDS, BaseConnector, Window, make_bundle
from engine.connectors.common import frame
from engine.connectors.fixture import FixtureWorld
from engine.connectors.github import GitHub
from engine.connectors.holidays import Holidays
from engine.connectors.mock_ads import MockAds
from engine.connectors.registry import NoSource, Registry
from engine.connectors.statuspages import StatusPages
from engine.connectors.stripe_conn import Stripe, payment_row
from engine.connectors.tavily_conn import Tavily
from engine.connectors.vercel import Vercel
from engine.connectors.whydunit_events import WhydunitEvents
from engine.fixtures.world import WorldSpec, generate
from engine.mock_ads import store as ads_store

W = Window(datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 8, tzinfo=UTC))


def schema_ok(bundle):
    assert set(KIND_SCHEMAS[bundle.kind]) <= set(bundle.frame.columns)
    assert bundle.id.startswith("ev_") and bundle.summary and 1 <= bundle.tier <= 6


@respx.mock
async def test_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "t")
    respx.get("https://api.vercel.com/v6/deployments").mock(
        return_value=httpx.Response(
            200,
            json={
                "deployments": [
                    {
                        "uid": "dpl_1",
                        "url": "acme-abc.vercel.app",
                        "created": 1759400000000,
                        "readyState": "READY",
                        "meta": {
                            "githubCommitSha": "abc123",
                            "githubCommitMessage": "refactor(signup): defer",
                            "githubCommitAuthorLogin": "sam",
                            "githubCommitRef": "main",
                        },
                    }
                ],
                "pagination": {"next": None},
            },
        )
    )
    b = await Vercel().fetch("deploys", W)
    schema_ok(b)
    assert b.frame["url"][0] == "https://acme-abc.vercel.app" and b.frame["git_sha"][0] == "abc123"


@respx.mock
async def test_github_commits_and_compare(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    respx.get(url__regex=r".*/commits.*").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "sha": "abcdef1234567890",
                    "html_url": "https://github.com/x/y/commit/abcdef1",
                    "commit": {
                        "message": "refactor(signup): defer form hydration until idle\n\nbody",
                        "committer": {"date": "2026-10-05T10:00:00Z"},
                        "author": {"name": "Sam"},
                    },
                    "author": {"login": "sam"},
                }
            ],
        )
    )
    gh = GitHub(repo="x/y")
    b = await gh.fetch("deploys", W)
    schema_ok(b)
    assert b.frame["commit_message"][0] == "refactor(signup): defer form hydration until idle"

    def compare(request):
        if request.headers["accept"] == "application/vnd.github.diff":
            return httpx.Response(200, text="diff --git a/x b/x\n+requestIdleCallback")
        return httpx.Response(
            200,
            json={
                "html_url": "https://github.com/x/y/compare/a...b",
                "commits": [],
                "files": [{"filename": "app/signup/SignupForm.tsx", "additions": 12, "deletions": 1}],
            },
        )

    respx.get(url__regex=r".*/compare/.*").mock(side_effect=compare)
    c = await gh.compare("a", "b")
    assert "requestIdleCallback" in c["diff"] and c["files"][0]["additions"] == 12


def test_stripe_payment_rows():
    ok = payment_row(
        {
            "id": "pi_1",
            "created": 1759400000,
            "amount": 1200,
            "currency": "usd",
            "status": "succeeded",
            "metadata": {"country": "BR"},
            "latest_charge": {
                "outcome": {"type": "authorized"},
                "payment_method_details": {"card": {"brand": "visa", "country": "US"}},
            },
        }
    )
    assert ok["outcome_type"] == "authorized" and ok["decline_code"] is None and ok["country"] == "BR"
    bad = payment_row(
        {
            "id": "pi_2",
            "created": 1759400000,
            "amount": 1200,
            "currency": "usd",
            "status": "requires_payment_method",
            "metadata": {"country": "BR"},
            "last_payment_error": {"type": "card_error", "decline_code": "do_not_honor"},
            "latest_charge": {
                "outcome": {"type": "issuer_declined", "reason": "generic_decline"},
                "payment_method_details": {"card": {"brand": "visa", "country": "BR"}},
            },
        }
    )
    assert bad["outcome_type"] == "issuer_declined" and bad["decline_code"] == "do_not_honor"


async def test_stripe_connector_with_fake_client(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")

    class Page:
        def auto_paging_iter(self):
            yield {
                "id": "pi_9",
                "created": 1759400000,
                "amount": 1200,
                "currency": "usd",
                "status": "succeeded",
                "metadata": {},
                "latest_charge": None,
            }

    class Client:
        class v1:  # noqa: N801
            class payment_intents:  # noqa: N801
                @staticmethod
                def list(params):
                    assert params["created"]["gte"] == int(W.start.timestamp())
                    return Page()

    b = await Stripe(client=Client()).fetch("payments", W)
    schema_ok(b)
    assert b.row_count == 1


async def test_stripe_refuses_live_keys(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_nope")
    with pytest.raises(RuntimeError, match="test mode"):
        _ = Stripe().client


async def test_tavily_with_fake_client():
    class Fake:
        async def search(self, query, **kw):
            assert kw["topic"] == "news" and kw["start_date"] == "2026-09-30"
            return {
                "results": [
                    {
                        "title": "Notes app outage",
                        "url": "https://n.example.com/a",
                        "content": "x",
                        "published_date": "Fri, 02 Oct 2026 10:00:00 GMT",
                        "score": 0.8,
                    },
                    {
                        "title": "Old",
                        "url": "https://n.example.com/b",
                        "content": "y",
                        "published_date": "Mon, 01 Jun 2026 10:00:00 GMT",
                    },
                ]
            }

    b = await Tavily(client=Fake()).fetch("world_news", W, {"query": "notes app outage"})
    schema_ok(b)
    assert b.row_count == 1 and b.artifacts[0].ref == "https://n.example.com/a"


@respx.mock
async def test_holidays_and_bundled_india():
    respx.get("https://date.nager.at/api/v3/PublicHolidays/2026/DE").mock(
        return_value=httpx.Response(
            200, json=[{"date": "2026-10-03", "name": "German Unity Day", "global": True}]
        )
    )
    respx.get("https://date.nager.at/api/v3/PublicHolidays/2026/IN").mock(return_value=httpx.Response(204))
    b = await Holidays().fetch(
        "holidays",
        Window(datetime(2026, 9, 28, tzinfo=UTC), datetime(2026, 10, 5, tzinfo=UTC)),
        {"countries": ["DE", "IN"]},
    )
    schema_ok(b)
    assert sorted(b.frame["name"].to_list()) == ["Gandhi Jayanti", "German Unity Day"]
    assert any("IN" in n for n in b.notes)


@respx.mock
async def test_statuspages():
    respx.get(url__regex=r"https://www\.githubstatus\.com/api/v2/incidents\.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "incidents": [
                    {
                        "name": "Degraded Actions",
                        "impact": "minor",
                        "started_at": "2026-10-03T10:00:00Z",
                        "resolved_at": "2026-10-03T11:00:00Z",
                        "shortlink": "https://stspg.io/x",
                        "components": [],
                    },
                    {
                        "name": "Old",
                        "impact": "major",
                        "started_at": "2026-08-01T10:00:00Z",
                        "resolved_at": "2026-08-01T11:00:00Z",
                        "shortlink": "https://stspg.io/y",
                        "components": [],
                    },
                ]
            },
        )
    )
    respx.get(url__regex=r"https://www\.vercel-status\.com/.*").mock(return_value=httpx.Response(500))
    b = await StatusPages().fetch("dependency_status", W)
    schema_ok(b)
    assert b.frame["name"].to_list() == ["Degraded Actions"]
    assert any("Vercel" in n for n in b.notes)


async def test_db_connectors(pg):
    proj = "acme"
    from engine.projects import create_project

    await create_project(proj, "Acme", "wd_acme_test")
    sid = "s_" + uuid.uuid4().hex[:12]
    t = datetime(2026, 10, 3, 12, tzinfo=UTC)
    await pg.execute(
        "INSERT INTO sessions (id, project_id, started_at, last_seen_at, browser, os, device, country, "
        "channel) VALUES (%s,%s,%s,%s,'Safari','iOS','mobile','BR','paid')",
        (sid, proj, t, t),
    )
    await pg.execute(
        "INSERT INTO events (event_id, project_id, name, ts, session_id, browser, os, device, country, "
        "channel) VALUES (%s,%s,'signup_started',%s,%s,'Safari','iOS','mobile','BR','paid')",
        (uuid.uuid4().hex, proj, t, sid),
    )
    b = await WhydunitEvents(proj).fetch(
        "funnel_events", W, {"names": ["signup_started"], "segment": {"os": "iOS"}}
    )
    schema_ok(b)
    assert sid in b.frame["session_id"].to_list()
    from engine.connectors.replays import Replays

    s = await Replays(proj).fetch("sessions", W, {"segment": {"country": "BR"}})
    assert s.frame.filter(s.frame["session_id"] == sid)["signup_started"][0] is True

    await pg.execute(
        "INSERT INTO acme.helpdesk_tickets (created_at, email, subject, body) VALUES (%s, 'a@b.c', "
        "'Can''t sign up', 'Button does nothing')",
        (t,),
    )
    await pg.execute(
        "INSERT INTO acme.reviews (created_at, platform, rating, body) VALUES (%s, 'app_store', 1, 'broken')",
        (t,),
    )
    await pg.execute(
        "INSERT INTO acme.payment_attempts (id, created_at, amount_cents, provider, outcome, decline_code, "
        "card_country) VALUES (%s, %s, 1200, 'mock', 'declined', 'do_not_honor', 'BR')",
        ("pa_" + uuid.uuid4().hex[:10], t),
    )
    for conn, kind in [
        (Helpdesk(), "support_tickets"),
        (Reviews(), "reviews"),
        (AcmePaymentLog(), "payments"),
    ]:
        bb = await conn.fetch(kind, W)
        schema_ok(bb)
        assert bb.row_count >= 1
    assert AcmePaymentLog.tier == 2


async def test_mock_ads_connector_and_no_api_mode(pg):
    await pg.execute("TRUNCATE mock_ads.hourly_stats, mock_ads.change_events, mock_ads.campaigns CASCADE")
    await ads_store.seed_campaigns()
    await ads_store.set_api_enabled(True)
    now = datetime.now(UTC)
    await ads_store.set_budget("1002", 150, user_email="jordan@acme-notes.test", client_type="WEB")
    from engine.mock_ads.model import HourStats

    await ads_store.record_hours(
        [HourStats("1002", now.replace(minute=0, second=0, microsecond=0), 900, 40, 18.5, True)]
    )
    w = Window(now - timedelta(days=1), now + timedelta(hours=1))
    c = MockAds()
    assert await c.available()
    perf = await c.fetch("ad_performance", w)
    changes = await c.fetch("ad_changes", w)
    schema_ok(perf)
    schema_ok(changes)
    assert perf.frame["budget_limited"].any()
    assert changes.frame["new_value"][0] == 150.0 and "jordan@acme-notes.test" in changes.summary
    await ads_store.set_api_enabled(False)
    assert not await MockAds().available()
    await ads_store.set_api_enabled(True)


class _Flaky(BaseConnector):
    name, tier, kinds = "flaky", 1, ("payments",)

    async def available(self):
        return True

    async def fetch(self, kind, window, filters=None):
        raise httpx.ConnectError("boom")


class _Backup(BaseConnector):
    name, tier, kinds = "backup", 3, ("payments",)

    async def available(self):
        return True

    async def _fetch_payments(self, window, filters):
        return make_bundle("payments", self, frame([], "payments"), window, summary="from csv")


async def test_registry_ladder_and_cannot_determine(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    reg = Registry([Stripe(), _Flaky(), _Backup()])
    b = await reg.fetch("payments", W)
    assert b.connector == "backup" and b.tier == 3 and b.confidence < 1
    assert "flaky" in b.notes[0] and "stripe" in b.notes[0]
    with pytest.raises(NoSource) as e:
        await reg.fetch("world_news", W, {"query": "x"})
    assert "world_news" in str(e.value)
    steps = await reg.ladder("payments")
    assert [s.connector for s in steps] == ["stripe", "flaky", "backup"] and not steps[0].available


@pytest.fixture(scope="module")
def small_world(tmp_path_factory):
    return generate(
        WorldSpec.preset("3inc"), tmp_path_factory.mktemp("w") / "3inc.duckdb", ground_truth=False
    )


async def test_fixture_connector_all_kinds(small_world):
    fw = FixtureWorld(small_world.path)
    case = await fw.case_spec()
    w = Window(datetime.fromisoformat(case["baseline_start"]), datetime.fromisoformat(case["window_end"]))
    reg = Registry([fw], mode="fixture")
    for kind in KINDS:
        b = await reg.fetch(kind, w, {"query": "notes"} if kind == "world_news" else {})
        schema_ok(b)
    deploys = (await reg.fetch("deploys", w)).frame
    bad = [d for d in deploys.to_dicts() if d["commit_message"].startswith("refactor(signup)")][0]
    diff = await fw.compare("prev", bad["git_sha"])
    assert "requestIdleCallback" in diff["diff"]
    flows = await fw.flow_results([bad["id"]])
    assert {f["probe"]: f["ok"] for f in flows}["webkit-mobile"] is False
    sess = (await reg.fetch("sessions", w, {"has_replay": True})).frame
    rec = await fw.recording(sess["session_id"][0])
    assert rec[0]["type"] == 4 and rec[1]["type"] == 2
