"""Ads dynamics for the SIMULATED ad platform: demand by hour, CPC noise, and daily budget caps.

Standard (non-paced) delivery: a campaign spends as clicks arrive until it reaches its daily budget,
then stops serving for the rest of the day ("limited by budget"). Lower the budget enough and it caps
around midday every day, so paid traffic falls in the afternoon.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from engine.world.model import HOURLY, WEEKDAY


@dataclass
class Campaign:
    id: str
    name: str
    daily_budget: float  # USD
    demand_clicks_per_day: float  # clicks it would get with an unlimited budget
    avg_cpc: float  # USD
    ctr: float = 0.045
    status: str = "ENABLED"


DEFAULT_CAMPAIGNS = [
    Campaign("1001", "Search · Brand", daily_budget=60.0, demand_clicks_per_day=160, avg_cpc=0.24, ctr=0.11),
    Campaign(
        "1002", "Search · Generic", daily_budget=450.0, demand_clicks_per_day=760, avg_cpc=0.44, ctr=0.038
    ),
]


@dataclass
class HourStats:
    campaign_id: str
    hour: datetime
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    budget_limited: bool = False
    click_times: list[datetime] = field(default_factory=list)


def simulate(
    campaign: Campaign,
    start: datetime,
    end: datetime,
    *,
    spent_before: float,
    budget_at: Callable[[datetime], float] | None = None,
    rng: np.random.Generator,
    enabled_at: Callable[[datetime], bool] | None = None,
) -> list[HourStats]:
    """Simulate [start, end) for one campaign. `spent_before` is spend earlier on start's day.

    `budget_at(t)` returns the daily budget in effect at t (budget changes take effect immediately);
    `enabled_at(t)` returns False while the campaign is paused. Demand and CPCs are drawn before the
    budget is applied, so the same seed with a different budget is an exact counterfactual.
    """
    out: list[HourStats] = []
    spent = spent_before
    day = start.date()
    t = start
    while t < end:
        if t.date() != day:
            day, spent = t.date(), 0.0
        nxt = min(end, (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
        hour = t.replace(minute=0, second=0, microsecond=0)
        stats = HourStats(campaign.id, hour)
        span = (nxt - t).total_seconds()
        lam = campaign.demand_clicks_per_day * span / 86400.0 * HOURLY[t.hour] * WEEKDAY[t.weekday()]
        n = int(rng.poisson(lam))
        offsets = np.sort(rng.uniform(0, span, n))
        cpcs = campaign.avg_cpc * rng.lognormal(0, 0.25, n)
        imp_u = rng.random()
        if enabled_at is None or enabled_at(t):
            budget_now = budget_at(t) if budget_at else campaign.daily_budget
            if budget_now - spent < campaign.avg_cpc * 0.5:
                stats.budget_limited = True
            else:
                for off, cpc in zip(offsets, cpcs, strict=True):
                    ct = t + timedelta(seconds=float(off))
                    budget = budget_at(ct) if budget_at else campaign.daily_budget
                    if spent + cpc > budget:
                        stats.budget_limited = True
                        break
                    spent += float(cpc)
                    stats.clicks += 1
                    stats.cost += float(cpc)
                    stats.click_times.append(ct)
            served = stats.clicks / max(n, 1) if stats.budget_limited else 1.0
            expected_imps = lam / campaign.ctr * served
            # Normal approximation from a pre-drawn uniform keeps the draw count fixed.
            stats.impressions = max(
                0, int(round(expected_imps + (imp_u - 0.5) * 2 * np.sqrt(max(expected_imps, 1))))
            )
        out.append(stats)
        t = nxt
    return out
