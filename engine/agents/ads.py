"""The Ads detective: spend, clicks and budget limits by campaign and day, plus the account's change history."""

from __future__ import annotations

from datetime import timedelta

import polars as pl

from engine.agents.base import Detective, Tool
from engine.connectors.base import Window


class AdsDetective(Detective):
    def __init__(self, ctx):
        super().__init__(
            ctx,
            name="ads",
            title="Ads detective",
            mission="You own paid acquisition: spend, impressions, clicks and budget-limited status by "
            "campaign and day, and every change made in the ad account.",
        )

    async def playbook(self) -> None:
        ctx = self.ctx
        w = Window(ctx.case.baseline_start - timedelta(days=1), ctx.case.window_end)
        perf = await self.fetch("ad_performance", w)
        changes = await self.fetch(
            "ad_changes", Window(ctx.case.baseline_start - timedelta(days=7), ctx.case.window_end)
        )
        if perf is None:
            return
        df = perf.frame.with_columns(pl.col("hour").dt.convert_time_zone("UTC"))
        daily = (
            df.group_by([pl.col("hour").dt.date().alias("day"), "campaign_id", "campaign_name"])
            .agg(
                pl.col("clicks").sum(),
                pl.col("cost").sum(),
                pl.col("impressions").sum(),
                pl.col("budget_limited").any().alias("limited"),
                pl.col("hour").filter(pl.col("budget_limited")).min().alias("first_limited"),
            )
            .sort(["day", "campaign_id"])
        )
        an = await self.analysis(
            "ads_daily",
            daily,
            "Daily spend, clicks and budget-limited status per campaign",
            [perf.id] + ([changes.id] if changes else []),
            w,
        )

        def per_day(period_start, period_end, cid=None):
            s = df.filter((pl.col("hour") >= period_start) & (pl.col("hour") < period_end))
            if cid:
                s = s.filter(pl.col("campaign_id") == cid)
            days = (period_end - period_start).total_seconds() / 86400
            return s["clicks"].sum() / days, s["cost"].sum() / days

        c0, s0 = per_day(ctx.case.baseline_start, ctx.case.baseline_end)
        c1, s1 = per_day(ctx.case.window_start, ctx.case.window_end)
        m_c0 = ctx.metric("paid clicks per day, baseline", c0, "per_day", [perf.id])
        m_c1 = ctx.metric("paid clicks per day, window", c1, "per_day", [perf.id])
        m_s0 = ctx.metric("ad spend per day, baseline", s0, "currency", [perf.id])
        m_s1 = ctx.metric("ad spend per day, window", s1, "currency", [perf.id])

        limited_win = daily.filter(pl.col("limited") & (pl.col("day") >= ctx.case.window_start.date()))
        budget_changes = changes.frame.to_dicts() if changes is not None else []
        cuts = [
            c
            for c in budget_changes
            if c.get("new_value") is not None
            and c.get("old_value") is not None
            and c["new_value"] < c["old_value"]
        ]
        if not limited_win.height and not cuts:
            self.add_finding(
                f"Paid acquisition looks normal: {c0:.0f} → {c1:.0f} clicks per day, spend ${s0:.0f} → ${s1:.0f} per "
                "day, no campaign limited by budget and no budget cuts in the account history.",
                [perf.id, an.id] + ([changes.id] if changes else []),
                [m_c0.id, m_c1.id, m_s0.id, m_s1.id],
                confidence=0.85,
            )
            return
        if cuts:
            cut = max(cuts, key=lambda c: c["old_value"] - c["new_value"])
            cid = cut["campaign_id"]
            ts = cut["ts"]
            after = daily.filter((pl.col("campaign_id") == cid) & (pl.col("day") > ts.date()))
            capped_days = after.filter(pl.col("limited"))
            cap_hours = [r.hour for r in capped_days["first_limited"].to_list() if r is not None]
            k0, _ = per_day(ctx.case.baseline_start, ctx.case.baseline_end, cid)
            k1, _ = per_day(max(ts, ctx.case.window_start), ctx.case.window_end, cid)
            m_old = ctx.metric(
                f"{cut['campaign_name']} daily budget before", cut["old_value"], "currency", [changes.id]
            )
            m_new = ctx.metric(
                f"{cut['campaign_name']} daily budget after", cut["new_value"], "currency", [changes.id]
            )
            m_k0 = ctx.metric(f"{cut['campaign_name']} clicks per day, baseline", k0, "per_day", [perf.id])
            m_k1 = ctx.metric(
                f"{cut['campaign_name']} clicks per day, after the change", k1, "per_day", [perf.id]
            )
            refs = [m_old.id, m_new.id, m_k0.id, m_k1.id]
            cap_txt = ""
            if capped_days.height:
                m_cd = ctx.metric(
                    f"{cut['campaign_name']} days limited by budget since the change",
                    capped_days.height,
                    "count",
                    [an.id],
                )
                m_ch = ctx.metric(
                    f"{cut['campaign_name']} typical hour it hits the budget (UTC)",
                    sorted(cap_hours)[len(cap_hours) // 2] if cap_hours else 0,
                    "hours",
                    [an.id],
                )
                refs += [m_cd.id, m_ch.id]
                cap_txt = (
                    f" Since then it has been limited by budget on {capped_days.height} of {after.height} full "
                    f"day(s), typically running out around {m_ch.value:.0f}:00 UTC."
                )
                m_ad = ctx.metric(
                    f"{cut['campaign_name']} full days since the change", after.height, "count", [an.id]
                )
                refs.append(m_ad.id)
            self.add_finding(
                f"{cut['user_email']} lowered the daily budget of “{cut['campaign_name']}” from ${cut['old_value']:.0f} to "
                f"${cut['new_value']:.0f} on {ts:%a %b %d %H:%M} UTC.{cap_txt} Its clicks fell from {k0:.0f} to {k1:.0f} "
                "per day.",
                [changes.id, perf.id, an.id],
                refs,
                confidence=0.95,
            )
            self.propose(
                f"The “{cut['campaign_name']}” budget cut capped paid traffic",
                "traffic",
                {"channel": "paid"},
                ts,
                [],
            )
        elif limited_win.height:
            self.add_finding(
                f"Campaigns were limited by budget during the window although no budget change was recorded; paid clicks "
                f"went from {c0:.0f} to {c1:.0f} per day.",
                [perf.id, an.id],
                [m_c0.id, m_c1.id],
                kind="inference",
                confidence=0.7,
            )

    def tools(self) -> list[Tool]:
        return []
