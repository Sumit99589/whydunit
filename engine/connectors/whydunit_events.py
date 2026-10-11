"""Tier 1: Whydunit's own event data (from the snippet), in Postgres."""

from __future__ import annotations

from typing import Any

from engine import db
from engine.connectors.base import BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame, segment_filters, top_counts

SEGMENT_COLS = {"browser", "os", "device", "country", "channel", "path"}


class WhydunitEvents(BaseConnector):
    name = "whydunit_events"
    tier = 1
    kinds = ("funnel_events",)

    def __init__(self, project_id: str = "acme"):
        self.project_id = project_id

    async def available(self) -> bool:
        try:
            await db.fetchrow("SELECT 1")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def _fetch_funnel_events(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        names = filters.get("names")
        seg_sql, seg_params = segment_filters(filters, SEGMENT_COLS)
        sql = (
            "SELECT event_id, ts, name, session_id, anon_id, user_id, browser, os, device, country, channel, path "
            "FROM events WHERE project_id = %s"
        )
        params: list[Any] = [self.project_id]
        if window:
            sql += " AND ts >= %s AND ts < %s"
            params += [window.start, window.end]
        if names:
            sql += " AND name = ANY(%s)"
            params.append(list(names))
        sql += seg_sql + " ORDER BY ts"
        rows = await db.fetch(sql, params + seg_params)
        df = frame(rows, "funnel_events")
        summary = f"{df.height:,} funnel events from Whydunit's own tracking, {fmt_window(window)}" + (
            f": {top_counts(df['name'].to_list())}" if df.height else ""
        )
        return make_bundle(
            "funnel_events",
            self,
            df,
            window,
            query={"names": names, "segment": filters.get("segment")},
            summary=summary,
            data_ref={"source": "postgres:events", "project": self.project_id},
        )
