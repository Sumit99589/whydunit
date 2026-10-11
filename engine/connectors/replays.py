"""Tier 1: sessions and their rrweb recordings (own DB + blob storage)."""

from __future__ import annotations

import gzip
import json
from typing import Any

from engine import db
from engine.connectors.base import BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame, segment_filters
from engine.storage import get_blob_store

SEGMENT_COLS = {"browser", "os", "device", "country", "channel"}


class Replays(BaseConnector):
    name = "replays"
    tier = 1
    kinds = ("sessions",)

    def __init__(self, project_id: str = "acme"):
        self.project_id = project_id

    async def available(self) -> bool:
        try:
            await db.fetchrow("SELECT 1")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def _fetch_sessions(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        seg_sql, seg_params = segment_filters(filters, SEGMENT_COLS)
        sql = (
            "SELECT s.id AS session_id, s.started_at, s.last_seen_at, s.browser, s.os, s.device, s.country, "
            "s.channel, s.has_replay, s.synthetic, "
            "EXISTS (SELECT 1 FROM events e WHERE e.session_id = s.id AND e.name = 'signup_started') AS signup_started, "
            "EXISTS (SELECT 1 FROM events e WHERE e.session_id = s.id AND e.name = 'signup_completed') AS signup_completed "
            "FROM sessions s WHERE s.project_id = %s"
        )
        params: list[Any] = [self.project_id]
        if window:
            sql += " AND s.started_at >= %s AND s.started_at < %s"
            params += [window.start, window.end]
        if filters.get("has_replay"):
            sql += " AND s.has_replay"
        sql += seg_sql.replace(" AND ", " AND s.") + " ORDER BY s.started_at LIMIT %s"
        rows = await db.fetch(sql, params + seg_params + [int(filters.get("limit", 500_000))])
        df = frame(rows, "sessions")
        n_rep = int(df["has_replay"].sum()) if df.height else 0
        return make_bundle(
            "sessions",
            self,
            df,
            window,
            query=filters,
            summary=f"{df.height:,} sessions ({n_rep:,} with recordings), {fmt_window(window)}",
            data_ref={"source": "postgres:sessions"},
        )

    async def recording(self, session_id: str) -> list[dict[str, Any]]:
        """The full rrweb event stream for one session (chunks concatenated in order)."""
        rows = await db.fetch(
            "SELECT blob_key FROM replays WHERE session_id = %s ORDER BY chunk_index", (session_id,)
        )
        store = get_blob_store()
        events: list[dict[str, Any]] = []
        for r in rows:
            events += json.loads(gzip.decompress(await store.get(r["blob_key"])))
        return events
