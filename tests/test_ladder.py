"""Stage 12: the rest of the ladder. CSV uploads (tier 3), screen reading in no-API mode (tier 4), ask a human (tier 6)."""

import io
import re
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

import httpx
import numpy as np
import polars as pl
import pytest

from engine.agents.ads import AdsDetective
from engine.api.app import create_app
from engine.connectors import NoSource, Registry
from engine.connectors.base import Window
from engine.connectors.csv_upload import CSVUpload, confirm_upload, heuristic_mapping, ingest_upload
from engine.connectors.fixture import FixtureWorld
from engine.connectors.mock_ads import MockAds
from engine.connectors.screen_reader import ScreenReader, changes_from_rows, performance_from_rows
from engine.connectors.stripe_conn import Stripe
from engine.fixtures.world import resolve_world
from engine.mock_ads import store as ads_store
from engine.mock_ads.model import DEFAULT_CAMPAIGNS, simulate
from engine.runtime import events as ev
from engine.runtime.context import CaseContext
from engine.runtime.schemas import Case
from engine.storage import LocalBlobStore, set_blob_store


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("NEBIUS_API_KEY", "")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from engine.runtime import llm as llm_mod

    llm_mod.set_llm(None)
    set_blob_store(LocalBlobStore(tmp_path))
    yield
    set_blob_store(None)
    llm_mod.set_llm(None)


def stripe_export_csv() -> bytes:
    """A Stripe-dashboard-style payments export built from the flagship world's payments."""
    fw = FixtureWorld(resolve_world("fixture:3inc"))
    df = fw._q("SELECT * FROM payments")
    out = df.select(
        pl.col("id"),
        pl.col("created").dt.strftime("%Y-%m-%d %H:%M:%S").alias("Created date (UTC)"),
        (pl.col("amount") / 100).map_elements(lambda x: f"{x:.2f}", return_dtype=pl.Utf8).alias("Amount"),
        pl.col("currency").str.to_uppercase().alias("Currency"),
        pl.when(pl.col("status") == "succeeded")
        .then(pl.lit("Paid"))
        .otherwise(pl.lit("Failed"))
        .alias("Status"),
        pl.col("decline_code").alias("Decline Reason"),
        pl.col("card_brand").alias("Card Brand"),
        pl.col("card_country").alias("Card Issue Country"),
        pl.col("metadata_country").alias("country (metadata)"),
    )
    buf = io.BytesIO()
    out.write_csv(buf)
    return buf.getvalue()


async def test_csv_upload_mapped_and_used(pg):
    data = stripe_export_csv()
    cols = pl.read_csv(io.BytesIO(data)).columns
    m = heuristic_mapping("payments", cols)
    assert m["created"] == "Created date (UTC)" and m["decline_code"] == "Decline Reason"
    assert m["card_country"] == "Card Issue Country" and m["country"] == "country (metadata)"
    up = await ingest_upload("payments", "stripe_export.csv", data)
    assert up["mapped_by"] == "rules" and up["row_count"] > 500
    p0 = up["preview"][0]
    assert (
        p0["amount"] == 1200
        and p0["currency"] == "usd"
        and p0["status"] in ("succeeded", "requires_payment_method")
    )
    reg = Registry([Stripe(), CSVUpload()])
    with pytest.raises(NoSource):  # not a source until confirmed
        await reg.fetch("payments", None)
    await confirm_upload(up["id"])
    b = await reg.fetch(
        "payments", Window(datetime(2026, 9, 17, tzinfo=UTC), datetime(2026, 9, 28, tzinfo=UTC))
    )
    assert b.connector == "csv_upload" and b.tier == 3 and b.confidence == 0.85
    br = b.frame.filter(pl.col("country") == "BR")
    late = br.filter(pl.col("created") >= datetime(2026, 9, 25, tzinfo=UTC))
    assert (late["outcome_type"] == "issuer_declined").mean() > 0.25
    assert "stripe" in b.notes[0]  # fell back from the Stripe API


class _Tables(HTMLParser):
    """Stand-in for the browser runner's capture: the dashboard's tables as rendered text."""

    def __init__(self):
        super().__init__()
        self.tables, self.cur, self.row, self.cell, self.in_cell = {}, None, None, "", False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and a.get("id"):
            self.cur = a["id"]
            self.tables[self.cur] = []
        elif tag == "tr" and self.cur:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.in_cell, self.cell = True, ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell:
            self.row.append(re.sub(r"\s+", " ", self.cell).strip())
            self.in_cell = False
        elif tag == "tr" and self.row is not None and self.cur:
            self.tables[self.cur].append(self.row)
            self.row = None
        elif tag == "table":
            self.cur = None

    def handle_data(self, data):
        if self.in_cell:
            self.cell += data


async def test_screen_reading_finds_budget_cap_in_no_api_mode(pg):
    # 14 days of simulated ad delivery with the Generic budget cut five days ago.
    await pg.execute("TRUNCATE mock_ads.hourly_stats, mock_ads.change_events, mock_ads.campaigns CASCADE")
    await ads_store.seed_campaigns()
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start = (now - timedelta(days=14)).replace(hour=0)
    cut_at = (now - timedelta(days=5)).replace(hour=21)
    for c in DEFAULT_CAMPAIGNS:
        hours = simulate(
            c,
            start,
            now,
            spent_before=0,
            rng=np.random.default_rng(int(c.id)),
            budget_at=(lambda t: 150.0 if t >= cut_at else 450.0) if c.id == "1002" else None,
        )
        await ads_store.record_hours(hours)
    await ads_store.set_budget(
        "1002", 150, user_email="jordan@acme-notes.test", client_type="GOOGLE_ADS_WEB_CLIENT", at=cut_at
    )
    await ads_store.set_api_enabled(False)  # no-API mode
    app = create_app()

    async def capture(pages):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://e") as c:
            html = (await c.get("/mock-ads/", params={"days": 21})).text
        t = _Tables()
        t.feed(html)
        return {
            "pages": [
                {
                    "url": pages[0]["url"],
                    "screenshot_key": "runs/t/full.png",
                    "sections": [
                        {
                            "selector": "#daily",
                            "screenshot_key": "runs/t/daily.png",
                            "rows": t.tables["daily"],
                        },
                        {
                            "selector": "#changes",
                            "screenshot_key": "runs/t/changes.png",
                            "rows": t.tables["changes"],
                        },
                    ],
                }
            ]
        }

    case = Case(
        world="live",
        window_start=now - timedelta(days=4),
        window_end=now,
        baseline_start=now - timedelta(days=11),
        baseline_end=now - timedelta(days=7),
    )
    await ev.save_case(case)
    log = await ev.CaseLog(case.id).init()
    reg = Registry(
        [MockAds(), ScreenReader(dashboard_url="http://engine/mock-ads/?days=21", capture=capture)]
    )
    ctx = CaseContext(case, reg, log)
    rep = await AdsDetective(ctx).run()
    await ads_store.set_api_enabled(True)
    assert rep.findings, rep
    f = rep.findings[0]
    assert "from $450 to $150" in f.claim and "screen reading" in f.claim and "limited by budget" in f.claim
    assert f.confidence <= 0.6  # tier 4 evidence downgrades confidence
    assert any("screen_reader" in c and "tier 4" in c for c in rep.checked)
    assert rep.hypotheses[0].effect.segment == {"channel": "paid"}


def test_dashboard_row_parsers():
    perf = performance_from_rows(
        [
            ["Date", "Campaign", "Impr.", "Clicks", "Cost", "Status"],
            ["2026-10-08", "Search · Generic", "8,123", "341", "$150.02", "Limited by budget from 12:00"],
        ]
    )
    assert perf[0]["clicks"] == 341 and perf[0]["budget_limited"] and perf[0]["first_limited_hour"] == 12
    ch = changes_from_rows(
        [
            ["When", "Campaign", "Change", "Old → New", "User"],
            [
                "2026-10-06 21:00 UTC",
                "Search · Generic",
                "Budget",
                "$450.00 → $150.00",
                "jordan@acme-notes.test",
            ],
        ]
    )
    assert ch[0]["old_value"] == 450 and ch[0]["new_value"] == 150 and ch[0]["ts"].hour == 21


async def test_ask_a_human_when_no_source(pg):
    case = Case(
        world="live",
        window_start=datetime(2026, 10, 1, tzinfo=UTC),
        window_end=datetime(2026, 10, 4, tzinfo=UTC),
        baseline_start=datetime(2026, 9, 24, tzinfo=UTC),
        baseline_end=datetime(2026, 9, 27, tzinfo=UTC),
    )
    await ev.save_case(case)
    ctx = CaseContext(case, Registry([]), await ev.CaseLog(case.id).init())
    with pytest.raises(NoSource):
        await ctx.fetch("reviews", ctx.case_window, detective="voice")
    req = await pg.fetchrow("SELECT * FROM evidence_requests WHERE case_id = %s", (case.id,))
    assert req["kind"] == "reviews" and req["status"] == "open"
    types = [e["type"] for e in await ev.events_since(case.id)]
    assert "evidence_requested" in types


async def test_screen_reader_omni_path(pg, tmp_path):
    from engine.runtime.cache import DiskCache
    from engine.runtime.llm import LLM
    from engine.storage import get_blob_store

    class Vision:
        async def complete(self, req):
            text = req["messages"][-1]["content"][0]["text"]
            rows = (
                [
                    ["Date", "Campaign", "Impr.", "Clicks", "Cost", "Status"],
                    [
                        "2026-10-08",
                        "Search · Generic",
                        "8,123",
                        "341",
                        "$150.02",
                        "Limited by budget from 12:00",
                    ],
                ]
                if "Daily performance" in text
                else [
                    ["When", "Campaign", "Change", "Old → New", "User"],
                    [
                        "2026-10-06 21:00 UTC",
                        "Search · Generic",
                        "Budget",
                        "$450.00 → $150.00",
                        "jordan@acme-notes.test",
                    ],
                ]
            )
            import json as _j

            return {
                "choices": [{"message": {"content": _j.dumps({"rows": rows})}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 80},
            }

    store = get_blob_store()
    await store.put("runs/o/daily.png", b"\x89PNG fake")
    await store.put("runs/o/changes.png", b"\x89PNG fake")

    async def capture(pages):
        return {
            "pages": [
                {
                    "url": "x",
                    "screenshot_key": "runs/o/daily.png",
                    "sections": [
                        {"selector": "#daily", "screenshot_key": "runs/o/daily.png", "rows": []},
                        {"selector": "#changes", "screenshot_key": "runs/o/changes.png", "rows": []},
                    ],
                }
            ]
        }

    llm = LLM(backend=Vision(), cache=DiskCache(directory=tmp_path, enabled=False))
    sr = ScreenReader(dashboard_url="http://d/", capture=capture, llm=llm)
    perf = await sr.fetch("ad_performance", None)
    ch = await sr.fetch("ad_changes", None)
    assert perf.tier == 4 and "Nemotron Nano Omni" in perf.summary
    assert perf.frame["clicks"][0] == 341 and perf.frame["first_limited_hour"][0] == 12
    assert ch.frame["new_value"][0] == 150 and perf.artifacts[0].type == "screenshot"
