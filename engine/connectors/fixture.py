"""Fixture mode: every evidence kind is served from a fixture world's DuckDB file, with the same schemas
(and the same tool methods: diffs, flow results, recordings) as the live connectors."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from engine.connectors.base import KINDS, Artifact, BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, top_counts

SEG_COLS = {"browser", "os", "device", "country", "channel", "path"}
STOP = {"the", "a", "an", "of", "for", "and", "or", "in", "on", "to", "with", "news", "is", "at", "by"}


class FixtureWorld(BaseConnector):
    tier = 1
    kinds = KINDS

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.name = f"fixture:{self.path.stem}"

    async def available(self) -> bool:
        return self.path.exists()

    def tier_for(self, kind: str) -> int:
        return 1

    # ------------------------------------------------------------------ helpers
    def _q(self, sql: str, params: list[Any] | None = None) -> pl.DataFrame:
        with duckdb.connect(str(self.path), read_only=True, config={"TimeZone": "UTC"}) as con:
            cur = con.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return (
            pl.DataFrame([dict(zip(cols, r, strict=True)) for r in rows], infer_schema_length=None)
            if rows
            else pl.DataFrame({c: [] for c in cols})
        )

    async def q(self, sql: str, params: list[Any] | None = None) -> pl.DataFrame:
        return await asyncio.to_thread(self._q, sql, params)

    @staticmethod
    def _w(col: str, window: Window | None) -> tuple[str, list[Any]]:
        return (
            (f" WHERE {col} >= ? AND {col} < ?", [window.start, window.end])
            if window
            else (" WHERE true", [])
        )

    def meta(self) -> dict[str, Any]:
        with duckdb.connect(str(self.path), read_only=True) as con:
            return json.loads(con.execute("SELECT value FROM meta WHERE key = 'world'").fetchone()[0])

    def _bundle(
        self, kind: str, df: pl.DataFrame, window: Window | None, summary: str, **kw: Any
    ) -> EvidenceBundle:
        return make_bundle(
            kind,
            self,
            df,
            window,
            summary=summary,
            data_ref={"source": f"duckdb:{self.path.name}", **kw.pop("data_ref", {})},
            **kw,
        )

    # ------------------------------------------------------------------ kinds
    async def _fetch_funnel_events(self, window: Window | None, f: dict[str, Any]) -> EvidenceBundle:
        w, p = self._w("ts", window)
        if f.get("names"):
            w += " AND name IN (SELECT unnest(?))"
            p.append(list(f["names"]))
        for k, v in (f.get("segment") or {}).items():
            if k not in SEG_COLS:
                raise ValueError(f"cannot filter on {k!r}")
            w += f" AND {k} IN (SELECT unnest(?))"
            p.append(list(v) if isinstance(v, list | tuple) else [v])
        df = await self.q(
            "SELECT event_id, ts, name, session_id, anon_id, user_id, browser, os, device, country, "
            f"channel, path FROM events{w} ORDER BY ts",
            p,
        )
        return self._bundle(
            "funnel_events",
            df,
            window,
            query={"names": f.get("names"), "segment": f.get("segment")},
            summary=f"{df.height:,} funnel events, {fmt_window(window)}"
            + (f": {top_counts(df['name'].to_list())}" if df.height else ""),
        )

    async def _fetch_sessions(self, window: Window | None, f: dict[str, Any]) -> EvidenceBundle:
        w, p = self._w("s.started_at", window)
        if f.get("has_replay"):
            w += " AND s.has_replay"
        for k, v in (f.get("segment") or {}).items():
            if k not in SEG_COLS:
                raise ValueError(f"cannot filter on {k!r}")
            w += f" AND s.{k} IN (SELECT unnest(?))"
            p.append(list(v) if isinstance(v, list | tuple) else [v])
        df = await self.q(
            "SELECT s.id AS session_id, s.started_at, s.last_seen_at, s.browser, s.os, s.device, s.country, s.channel, "
            "s.has_replay, EXISTS (SELECT 1 FROM events e WHERE e.session_id = s.id AND e.name = 'signup_started') "
            "AS signup_started, EXISTS (SELECT 1 FROM events e WHERE e.session_id = s.id AND e.name = "
            f"'signup_completed') AS signup_completed FROM sessions s{w} ORDER BY s.started_at LIMIT ?",
            p + [int(f.get("limit", 500_000))],
        )
        n = int(df["has_replay"].sum()) if df.height else 0
        return self._bundle(
            "sessions",
            df,
            window,
            query=f,
            summary=f"{df.height:,} sessions ({n:,} with recordings), {fmt_window(window)}",
        )

    async def _fetch_deploys(self, window: Window | None, f: dict[str, Any]) -> EvidenceBundle:
        w, p = self._w("created_at", window)
        df = await self.q(
            "SELECT id, url, git_sha, created_at, commit_message, author, state, files_changed, "
            f"permanent_alias FROM deployments{w} ORDER BY created_at",
            p,
        )
        return self._bundle(
            "deploys", df, window, summary=f"{df.height} production deployments of Acme, {fmt_window(window)}"
        )

    async def _fetch_payments(self, window: Window | None, f: dict[str, Any]) -> EvidenceBundle:
        w, p = self._w("created", window)
        df = await self.q(
            "SELECT id, created, amount, currency, status, outcome_type, decline_code, error_code, "
            f"card_brand, card_country, metadata_country AS country FROM payments{w} ORDER BY created",
            p,
        )
        return self._bundle(
            "payments",
            df,
            window,
            summary=f"{df.height:,} payments, {fmt_window(window)}"
            + (f": {top_counts(df['outcome_type'].to_list())}" if df.height else ""),
        )

    async def _fetch_ad_performance(self, window: Window | None, f: dict[str, Any]) -> EvidenceBundle:
        w, p = self._w("h.hour", window)
        df = await self.q(
            "SELECT h.hour, h.campaign_id, c.name AS campaign_name, h.impressions, h.clicks, h.cost, "
            "h.budget_limited, c.daily_budget AS daily_budget_now FROM ads_hourly h "
            f"JOIN ads_campaigns c ON c.id = h.campaign_id{w} ORDER BY h.hour",
            p,
        )
        days = (
            df.filter(pl.col("budget_limited")).select(pl.col("hour").dt.date().unique()).height
            if df.height
            else 0
        )
        return self._bundle(
            "ad_performance",
            df,
            window,
            data_ref={"simulated": True},
            summary=f"Hourly ad performance (SIMULATED ad platform), {fmt_window(window)}; "
            + (f"budget-limited on {days} day(s)" if days else "never budget-limited"),
        )

    async def _fetch_ad_changes(self, window: Window | None, f: dict[str, Any]) -> EvidenceBundle:
        w, p = self._w("a.ts", window)
        df = await self.q(
            "SELECT a.ts, a.campaign_id, c.name AS campaign_name, 'daily_budget' AS field, a.old_value, "
            "a.new_value, a.user_email, a.client_type FROM ads_changes a JOIN ads_campaigns c "
            f"ON c.id = a.campaign_id{w} ORDER BY a.ts",
            p,
        )
        desc = "; ".join(
            f"{r['campaign_name']} budget ${r['old_value']:.0f}→${r['new_value']:.0f} by {r['user_email']}"
            for r in df.head(3).to_dicts()
        )
        return self._bundle(
            "ad_changes",
            df,
            window,
            summary=f"{df.height} ad account changes, {fmt_window(window)}" + (f": {desc}" if desc else ""),
        )

    async def _fetch_support_tickets(self, window: Window | None, f: dict[str, Any]) -> EvidenceBundle:
        w, p = self._w("created_at", window)
        df = await self.q(
            f"SELECT id, created_at, subject, body, channel, meta FROM tickets{w} ORDER BY created_at", p
        )
        return self._bundle(
            "support_tickets", df, window, summary=f"{df.height} support tickets, {fmt_window(window)}"
        )

    async def _fetch_reviews(self, window: Window | None, f: dict[str, Any]) -> EvidenceBundle:
        w, p = self._w("created_at", window)
        df = await self.q(
            f"SELECT id, created_at, platform, rating, title, body FROM reviews{w} ORDER BY created_at", p
        )
        return self._bundle("reviews", df, window, summary=f"{df.height} app reviews, {fmt_window(window)}")

    async def _fetch_world_news(self, window: Window | None, f: dict[str, Any]) -> EvidenceBundle:
        query = f.get("query") or ""
        w, p = self._w("published_at", window)
        df = await self.q(
            f"SELECT published_at, title, url, source, content FROM news{w} ORDER BY published_at", p
        )
        terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if t not in STOP and len(t) > 2]
        if df.height and terms:
            text = (df["title"] + " " + df["content"]).str.to_lowercase()
            score = sum(text.str.contains(t).cast(pl.Int32) for t in terms)
            df = (
                df.with_columns(score.alias("score"))
                .filter(pl.col("score") > 0)
                .sort("score", descending=True)
            )
        elif terms:
            df = df.with_columns(pl.lit(0).alias("score")).head(0)
        rows = df.to_dicts()
        return self._bundle(
            "world_news",
            df,
            window,
            query={"query": query},
            summary=f"News search “{query}”, {fmt_window(window)}: {df.height} result(s)"
            + ("" if df.height else " — nothing relevant found"),
            artifacts=[Artifact(type="link", ref=r["url"], caption=r["title"]) for r in rows[:5]],
            data_ref={"stand_in_for": "tavily"},
        )

    async def _fetch_holidays(self, window: Window | None, f: dict[str, Any]) -> EvidenceBundle:
        df = await self.q("SELECT date, country, name FROM holidays ORDER BY date")
        if window and df.height:
            lo, hi = window.start.date().isoformat(), window.end.date().isoformat()
            df = df.filter((pl.col("date") >= lo) & (pl.col("date") <= hi))
        listed = ", ".join(f"{r['name']} ({r['country']}, {r['date']})" for r in df.head(5).to_dicts())
        return self._bundle(
            "holidays", df, window, summary=f"Public holidays, {fmt_window(window)}: {listed or 'none'}"
        )

    async def _fetch_dependency_status(self, window: Window | None, f: dict[str, Any]) -> EvidenceBundle:
        df = await self.q(
            "SELECT service, name, impact, started_at, resolved_at, url FROM status_incidents "
            "ORDER BY started_at"
        )
        if window and df.height:
            df = df.filter(
                (pl.col("started_at") < window.end)
                & (pl.col("resolved_at").is_null() | (pl.col("resolved_at") >= window.start))
            )
        services = "GitHub, Vercel, Neon"
        return self._bundle(
            "dependency_status",
            df,
            window,
            summary=f"Status pages checked: {services}; {df.height} incident(s) {fmt_window(window)}",
        )

    # ------------------------------------------------------------------ tools
    async def compare(self, base: str, head: str) -> dict[str, Any]:
        df = await self.q(
            "SELECT git_sha, commit_message, diff, files_changed, url FROM deployments "
            "WHERE git_sha IN (?, ?)",
            [base, head],
        )
        row = next((r for r in df.to_dicts() if r["git_sha"] == head), None)
        if row is None:
            raise KeyError(head)
        return {
            "base": base,
            "head": head,
            "url": row["url"],
            "diff": row["diff"],
            "commits": [{"sha": head, "message": row["commit_message"]}],
            "files": [
                {"filename": x, "additions": None, "deletions": None}
                for x in json.loads(row["files_changed"])
            ],
            "artifact": Artifact(type="diff", caption=f"{base[:7]}…{head[:7]}"),
        }

    async def flow_results(
        self, deployment_ids: list[str], probes: list[str] | None = None
    ) -> list[dict[str, Any]]:
        df = await self.q(
            "SELECT f.*, d.url, d.created_at FROM flow_results f JOIN deployments d ON d.id = f.deployment_id "
            "WHERE f.deployment_id IN (SELECT unnest(?))",
            [deployment_ids],
        )
        rows = df.to_dicts()
        return [r for r in rows if not probes or r["probe"] in probes]

    async def recording(self, session_id: str) -> list[dict[str, Any]]:
        df = await self.q("SELECT events_json FROM replays WHERE session_id = ?", [session_id])
        if not df.height:
            raise KeyError(session_id)
        return json.loads(df["events_json"][0])

    async def case_spec(self) -> dict[str, Any]:
        return (await asyncio.to_thread(self.meta))["case"]
