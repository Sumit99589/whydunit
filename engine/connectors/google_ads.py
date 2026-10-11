"""Tier 1 stub: real Google Ads. Same interface as MockAds; needs a developer token (not built for the demo)."""

from __future__ import annotations

from typing import Any

from engine.connectors.base import BaseConnector, EvidenceBundle, Window


class GoogleAds(BaseConnector):
    """To make this real: apply for a Google Ads API developer token, create OAuth credentials, then map
    GAQL `campaign` + `metrics` (segmented by `segments.hour`) and `change_event` resources to the same
    ad_performance / ad_changes schemas that MockAds returns. Nothing else in Whydunit changes."""

    name = "google_ads"
    tier = 1
    priority = 5
    kinds = ("ad_performance", "ad_changes")
    needs_env = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_REFRESH_TOKEN")

    async def available(self) -> bool:
        return False

    async def fetch(
        self, kind: str, window: Window | None, filters: dict[str, Any] | None = None
    ) -> EvidenceBundle:
        raise NotImplementedError("GoogleAds connector is a documented stub; see class docstring")
