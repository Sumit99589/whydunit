"""Persistence for the SIMULATED ad platform (Postgres schema `mock_ads`)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from engine import db
from engine.mock_ads.model import DEFAULT_CAMPAIGNS, Campaign, HourStats

MICROS = 1_000_000


async def seed_campaigns(campaigns: list[Campaign] = DEFAULT_CAMPAIGNS) -> None:
    for c in campaigns:
        await db.execute(
            """INSERT INTO mock_ads.campaigns (id, name, status, daily_budget_micros, demand_clicks_per_day, avg_cpc, ctr)
               VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (c.id, c.name, c.status, int(c.daily_budget * MICROS), c.demand_clicks_per_day, c.avg_cpc, c.ctr),
        )


async def campaigns() -> list[Campaign]:
    rows = await db.fetch("SELECT * FROM mock_ads.campaigns ORDER BY id")
    return [
        Campaign(
            r["id"],
            r["name"],
            r["daily_budget_micros"] / MICROS,
            r["demand_clicks_per_day"],
            r["avg_cpc"],
            r["ctr"],
            r["status"],
        )
        for r in rows
    ]


async def set_budget(
    campaign_id: str, amount: float, *, user_email: str, client_type: str, at: datetime | None = None
) -> dict[str, Any]:
    async with db.connection() as conn, conn.transaction():
        cur = await conn.execute(
            "SELECT daily_budget_micros FROM mock_ads.campaigns WHERE id = %s FOR UPDATE", (campaign_id,)
        )
        row = await cur.fetchone()
        if not row:
            raise KeyError(campaign_id)
        old, new = row["daily_budget_micros"], int(round(amount * MICROS))
        await conn.execute(
            "UPDATE mock_ads.campaigns SET daily_budget_micros = %s, updated_at = now() WHERE id = %s",
            (new, campaign_id),
        )
        cur = await conn.execute(
            """INSERT INTO mock_ads.change_events (change_date_time, campaign_id, change_resource_type,
                   resource_change_operation, changed_fields, old_resource, new_resource, user_email, client_type)
               VALUES (COALESCE(%s, now()), %s, 'CAMPAIGN_BUDGET', 'UPDATE', 'amount_micros', %s, %s, %s, %s)
               RETURNING id, change_date_time""",
            (
                at,
                campaign_id,
                db.jsonb({"campaign_budget": {"amount_micros": old}}),
                db.jsonb({"campaign_budget": {"amount_micros": new}}),
                user_email,
                client_type,
            ),
        )
        ev = await cur.fetchone()
    return {
        "change_event_id": ev["id"],
        "at": ev["change_date_time"],
        "old": old / MICROS,
        "new": new / MICROS,
    }


async def budget_timeline(campaign_id: str, since: datetime) -> list[tuple[datetime, float]]:
    """[(effective_from, budget)] covering `since` onwards, reconstructed from change events."""
    current = await db.fetchrow(
        "SELECT daily_budget_micros FROM mock_ads.campaigns WHERE id = %s", (campaign_id,)
    )
    events = await db.fetch(
        """SELECT change_date_time, old_resource, new_resource FROM mock_ads.change_events
           WHERE campaign_id = %s AND change_resource_type = 'CAMPAIGN_BUDGET' AND change_date_time >= %s
           ORDER BY change_date_time""",
        (campaign_id, since),
    )
    if not events:
        return [(since, current["daily_budget_micros"] / MICROS)]
    tl = [(since, events[0]["old_resource"]["campaign_budget"]["amount_micros"] / MICROS)]
    tl += [
        (e["change_date_time"], e["new_resource"]["campaign_budget"]["amount_micros"] / MICROS)
        for e in events
    ]
    return tl


def budget_fn(timeline: list[tuple[datetime, float]]):
    def at(t: datetime) -> float:
        val = timeline[0][1]
        for ts, b in timeline:
            if ts <= t:
                val = b
        return val

    return at


async def spent_on_day(campaign_id: str, day_start: datetime, before: datetime) -> float:
    row = await db.fetchrow(
        """SELECT COALESCE(SUM(cost_micros), 0) AS c FROM mock_ads.hourly_stats
           WHERE campaign_id = %s AND hour >= %s AND hour < %s""",
        (campaign_id, day_start, before),
    )
    return float(row["c"]) / MICROS


async def record_hours(stats: list[HourStats]) -> None:
    """Add stats (ticks may cover partial hours, so values accumulate)."""
    async with db.connection() as conn, conn.transaction():
        for s in stats:
            await conn.execute(
                """INSERT INTO mock_ads.hourly_stats (campaign_id, hour, impressions, clicks, cost_micros, budget_limited)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (campaign_id, hour) DO UPDATE SET
                     impressions = mock_ads.hourly_stats.impressions + EXCLUDED.impressions,
                     clicks = mock_ads.hourly_stats.clicks + EXCLUDED.clicks,
                     cost_micros = mock_ads.hourly_stats.cost_micros + EXCLUDED.cost_micros,
                     budget_limited = mock_ads.hourly_stats.budget_limited OR EXCLUDED.budget_limited""",
                (s.campaign_id, s.hour, s.impressions, s.clicks, int(s.cost * MICROS), s.budget_limited),
            )


async def daily_report(start: date, end: date) -> list[dict[str, Any]]:
    """Rows shaped like a Google Ads campaign report segmented by date (end inclusive)."""
    rows = await db.fetch(
        """SELECT (h.hour AT TIME ZONE 'UTC')::date AS day, c.id, c.name, c.daily_budget_micros,
                  SUM(h.impressions) AS impressions, SUM(h.clicks) AS clicks, SUM(h.cost_micros) AS cost_micros,
                  BOOL_OR(h.budget_limited) AS limited,
                  MIN(EXTRACT(HOUR FROM h.hour AT TIME ZONE 'UTC')) FILTER (WHERE h.budget_limited) AS first_limited_hour
           FROM mock_ads.hourly_stats h JOIN mock_ads.campaigns c ON c.id = h.campaign_id
           WHERE h.hour >= %s AND h.hour < %s
           GROUP BY 1, 2, 3, 4 ORDER BY 1, 2""",
        (
            datetime.combine(start, time.min, tzinfo=UTC),
            datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC),
        ),
    )
    out = []
    for r in rows:
        out.append(
            {
                "segments.date": r["day"].isoformat(),
                "campaign.id": r["id"],
                "campaign.name": r["name"],
                "metrics.impressions": int(r["impressions"]),
                "metrics.clicks": int(r["clicks"]),
                "metrics.cost_micros": int(r["cost_micros"]),
                "campaign.primary_status_reasons": ["BUDGET_CONSTRAINED"] if r["limited"] else [],
                "metrics.first_budget_limited_hour": int(r["first_limited_hour"])
                if r["first_limited_hour"] is not None
                else None,
            }
        )
    return out


async def hourly_report(start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """SELECT h.*, c.name FROM mock_ads.hourly_stats h JOIN mock_ads.campaigns c ON c.id = h.campaign_id
           WHERE h.hour >= %s AND h.hour < %s ORDER BY h.hour, h.campaign_id""",
        (start, end),
    )
    return [
        {
            "segments.hour": r["hour"].isoformat(),
            "campaign.id": r["campaign_id"],
            "campaign.name": r["name"],
            "metrics.impressions": r["impressions"],
            "metrics.clicks": r["clicks"],
            "metrics.cost_micros": r["cost_micros"],
            "budget_limited": r["budget_limited"],
        }
        for r in rows
    ]


async def change_events(start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """SELECT e.*, c.name FROM mock_ads.change_events e JOIN mock_ads.campaigns c ON c.id = e.campaign_id
           WHERE change_date_time >= %s AND change_date_time < %s ORDER BY change_date_time""",
        (start, end),
    )
    return [
        {
            "change_event.change_date_time": r["change_date_time"].isoformat(),
            "change_event.change_resource_type": r["change_resource_type"],
            "change_event.resource_change_operation": r["resource_change_operation"],
            "change_event.changed_fields": r["changed_fields"],
            "change_event.old_resource": r["old_resource"],
            "change_event.new_resource": r["new_resource"],
            "change_event.user_email": r["user_email"],
            "change_event.client_type": r["client_type"],
            "campaign.id": r["campaign_id"],
            "campaign.name": r["name"],
        }
        for r in rows
    ]


async def api_enabled() -> bool:
    row = await db.fetchrow("SELECT value FROM mock_ads.settings WHERE key = 'api_enabled'")
    return bool(row["value"]) if row else True


async def set_api_enabled(on: bool) -> None:
    await db.execute(
        "INSERT INTO mock_ads.settings (key, value) VALUES ('api_enabled', %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (db.jsonb(on),),
    )
