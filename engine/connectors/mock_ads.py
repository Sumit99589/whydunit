"""Tier 1: the SIMULATED ad platform's Google-Ads-shaped API (in-process or over HTTP)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from engine.connectors.base import BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame
from engine.settings import env


class MockAds(BaseConnector):
    name = "mock_ads"
    tier = 1
    kinds = ("ad_performance", "ad_changes")

    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url or env("MOCK_ADS_URL")
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        if self.base_url or self.transport:
            return httpx.AsyncClient(
                base_url=self.base_url or "http://ads.local", transport=self.transport, timeout=30
            )
        from engine.api.app import create_app

        return httpx.AsyncClient(
            base_url="http://engine.local", transport=httpx.ASGITransport(app=create_app()), timeout=30
        )

    async def available(self) -> bool:
        try:
            async with self._client() as c:
                r = await c.get("/mock-ads/api/campaigns")
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def _fetch_ad_performance(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        if window is None:
            raise ValueError("ad_performance needs a window")
        async with self._client() as c:
            r = await c.get(
                "/mock-ads/api/reports/campaign_hourly",
                params={"start": window.start.isoformat(), "end": window.end.isoformat()},
            )
            r.raise_for_status()
            camps = {x["campaign.id"]: x for x in (await c.get("/mock-ads/api/campaigns")).json()["results"]}
        rows = [
            {
                "hour": datetime.fromisoformat(x["segments.hour"]),
                "campaign_id": x["campaign.id"],
                "campaign_name": x["campaign.name"],
                "impressions": x["metrics.impressions"],
                "clicks": x["metrics.clicks"],
                "cost": x["metrics.cost_micros"] / 1e6,
                "budget_limited": x["budget_limited"],
                "daily_budget_now": camps.get(x["campaign.id"], {}).get("campaign_budget.amount_micros", 0)
                / 1e6,
            }
            for x in r.json()["results"]
        ]
        df = frame(rows, "ad_performance")
        limited = sorted(
            {(row["campaign_name"], row["hour"].date().isoformat()) for row in rows if row["budget_limited"]}
        )
        summary = (
            f"Hourly ad performance for {len(camps)} campaigns (SIMULATED ad platform), {fmt_window(window)}; "
            + (f"budget-limited on {len(limited)} campaign-days" if limited else "never budget-limited")
        )
        return make_bundle(
            "ad_performance",
            self,
            df,
            window,
            summary=summary,
            data_ref={"source": "mock_ads:/api/reports/campaign_hourly", "simulated": True},
        )

    async def _fetch_ad_changes(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        params = {"start": window.start.isoformat(), "end": window.end.isoformat()} if window else {}
        async with self._client() as c:
            r = await c.get("/mock-ads/api/change_events", params=params)
            r.raise_for_status()
        rows = []
        for x in r.json()["results"]:
            old = x["change_event.old_resource"].get("campaign_budget", {}).get("amount_micros")
            new = x["change_event.new_resource"].get("campaign_budget", {}).get("amount_micros")
            rows.append(
                {
                    "ts": datetime.fromisoformat(x["change_event.change_date_time"]),
                    "campaign_id": x["campaign.id"],
                    "campaign_name": x["campaign.name"],
                    "field": "daily_budget",
                    "old_value": old / 1e6 if old is not None else None,
                    "new_value": new / 1e6 if new is not None else None,
                    "user_email": x["change_event.user_email"],
                    "client_type": x["change_event.client_type"],
                }
            )
        df = frame(rows, "ad_changes")
        desc = "; ".join(
            f"{r['campaign_name']} budget ${r['old_value']:.0f}→${r['new_value']:.0f} by {r['user_email']}"
            for r in rows[:3]
        )
        return make_bundle(
            "ad_changes",
            self,
            df,
            window,
            data_ref={"source": "mock_ads:/api/change_events"},
            summary=f"{df.height} ad account changes, {fmt_window(window)}" + (f": {desc}" if desc else ""),
        )
