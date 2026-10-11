"""Funnel decomposition: paid subs = traffic × signup rate × checkout rate × payment success rate.

Log-mean Divisia (LMDI): each factor's contribution is L(P1, P0) · ln(f1 / f0) with
L(a, b) = (a − b) / (ln a − ln b), so the contributions add up *exactly* to the total change.
Everything is per day, so baseline and window may have different lengths.
"""

from __future__ import annotations

import math
from typing import Any

import polars as pl

from engine.analysis.data import FACTOR_DENOM, FACTOR_STEP, FACTORS, Period, funnel_counts


def logmean(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.0
    return a if math.isclose(a, b) else (a - b) / (math.log(a) - math.log(b))


def factor_values(counts: dict[str, int], days: float) -> dict[str, float]:
    t = counts["visited"] / days
    return {
        "traffic": t,
        "signup_rate": counts["signed_up"] / counts["visited"] if counts["visited"] else 0.0,
        "checkout_rate": counts["checkout"] / counts["signed_up"] if counts["signed_up"] else 0.0,
        "payment_success_rate": counts["paid"] / counts["checkout"] if counts["checkout"] else 0.0,
    }


def decompose(sess: pl.DataFrame, baseline: Period, window: Period) -> dict[str, Any]:
    c0, c1 = funnel_counts(baseline.filter(sess)), funnel_counts(window.filter(sess))
    f0, f1 = factor_values(c0, baseline.days), factor_values(c1, window.days)
    p0, p1 = c0["paid"] / baseline.days, c1["paid"] / window.days
    lm = logmean(p1, p0)
    factors = []
    for name in FACTORS:
        a, b = f0[name], f1[name]
        lr = math.log(b / a) if a > 0 and b > 0 else float("-inf") if b == 0 and a > 0 else 0.0
        contrib = lm * lr if math.isfinite(lr) else -p0 if b == 0 else 0.0
        factors.append(
            {
                "factor": name,
                "step": FACTOR_STEP[name],
                "baseline": a,
                "window": b,
                "pct_change": (b / a - 1) if a > 0 else None,
                "log_ratio": lr if math.isfinite(lr) else None,
                "contribution_per_day": contrib,
            }
        )
    total = p1 - p0
    for f in factors:
        f["share_of_change"] = f["contribution_per_day"] / total if total else 0.0
    return {
        "metric": "paid_subs",
        "unit": "per day",
        "baseline": baseline.as_dict(),
        "window": window.as_dict(),
        "baseline_per_day": p0,
        "window_per_day": p1,
        "change_per_day": total,
        "pct_change": (p1 / p0 - 1) if p0 else None,
        "factors": factors,
        "counts": {"baseline": c0, "window": c1},
        "check_sum": sum(f["contribution_per_day"] for f in factors) - total,
    }


def denominator(factor: str) -> str | None:
    return FACTOR_DENOM.get(factor)
