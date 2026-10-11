"""Segment drill-down: which segments drive a factor's change, split into mix and rate effects.

For a rate r = Σ w_s r_s (w_s = segment's share of the denominator), the change splits symmetrically:
  Δr = Σ_s (w1_s − w0_s)·(r̄_s − r̄)   [mix]   +   Σ_s (r1_s − r0_s)·(w1_s + w0_s)/2   [rate]
where r̄_s is the segment's mean rate across both periods and r̄ the overall one. Because Σ Δw = 0, measuring
mix against the overall average leaves the sum unchanged (still exactly Δr) but stops a segment from
looking important merely because its share moved while its rate is ordinary. For traffic (a count) a segment's contribution is its
change in visitors per day.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from engine.analysis.data import DIMS, FACTOR_DENOM, FACTOR_STEP, Period, segment_mask


def _rate_table(sess: pl.DataFrame, period: Period, dim: str, num: str, den: str) -> pl.DataFrame:
    return (
        period.filter(sess)
        .filter(pl.col(den))
        .group_by(dim)
        .agg(pl.len().alias("den"), pl.col(num).sum().alias("num"))
    )


def factor_by_segment(
    sess: pl.DataFrame,
    factor: str,
    dim: str,
    baseline: Period,
    window: Period,
    within: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    s = sess.filter(segment_mask(within)) if within else sess
    if factor == "traffic":
        a = baseline.filter(s).group_by(dim).agg(pl.len().alias("n0"))
        b = window.filter(s).group_by(dim).agg(pl.len().alias("n1"))
        j = a.join(b, on=dim, how="full", coalesce=True).fill_null(0)
        rows = []
        for r in j.to_dicts():
            v0, v1 = r["n0"] / baseline.days, r["n1"] / window.days
            rows.append(
                {
                    "dim": dim,
                    "value": r[dim],
                    "baseline": v0,
                    "window": v1,
                    "pct_change": (v1 / v0 - 1) if v0 else None,
                    "mix": 0.0,
                    "rate": v1 - v0,
                    "contribution": v1 - v0,
                    "baseline_n": r["n0"],
                    "window_n": r["n1"],
                }
            )
    else:
        num, den = FACTOR_STEP[factor], FACTOR_DENOM[factor]
        a = _rate_table(s, baseline, dim, num, den).rename({"den": "d0", "num": "x0"})
        b = _rate_table(s, window, dim, num, den).rename({"den": "d1", "num": "x1"})
        j = a.join(b, on=dim, how="full", coalesce=True).fill_null(0)
        tot0, tot1 = max(int(j["d0"].sum()), 1), max(int(j["d1"].sum()), 1)
        avg = (j["x0"].sum() / tot0 + j["x1"].sum() / tot1) / 2
        rows = []
        for r in j.to_dicts():
            w0, w1 = r["d0"] / tot0, r["d1"] / tot1
            r0 = r["x0"] / r["d0"] if r["d0"] else None
            r1 = r["x1"] / r["d1"] if r["d1"] else None
            rr0 = r0 if r0 is not None else (r1 or 0.0)
            rr1 = r1 if r1 is not None else (r0 or 0.0)
            mix = (w1 - w0) * ((rr1 + rr0) / 2 - avg)
            rate = (rr1 - rr0) * (w1 + w0) / 2
            rows.append(
                {
                    "dim": dim,
                    "value": r[dim],
                    "baseline": r0,
                    "window": r1,
                    "pct_change": (r1 / r0 - 1) if r0 and r1 is not None else None,
                    "mix": mix,
                    "rate": rate,
                    "contribution": mix + rate,
                    "baseline_share": w0,
                    "window_share": w1,
                    "baseline_n": r["d0"],
                    "window_n": r["d1"],
                }
            )
    total = sum(r["contribution"] for r in rows)
    for r in rows:
        r["share_of_factor_change"] = r["contribution"] / total if total else 0.0
    return sorted(rows, key=lambda r: r["contribution"])


def drilldown(
    sess: pl.DataFrame,
    factor: str,
    baseline: Period,
    window: Period,
    dims: tuple[str, ...] = DIMS,
    top: int = 3,
    depth: int = 2,
    min_n: int = 30,
) -> list[dict[str, Any]]:
    """Rank segments across dimensions by how much of the factor's drop they explain; drill one level more
    into the top segments."""
    ranked = []
    for dim in dims:
        for r in factor_by_segment(sess, factor, dim, baseline, window):
            if r["baseline_n"] + r["window_n"] >= min_n:
                ranked.append(r)
    ranked.sort(key=lambda r: r["contribution"])
    out = []
    for r in ranked[:top]:
        item = dict(r)
        if depth > 1:
            within = {r["dim"]: r["value"]}
            subs = []
            for dim in dims:
                if dim == r["dim"]:
                    continue
                parts = [
                    x
                    for x in factor_by_segment(sess, factor, dim, baseline, window, within)
                    if x["baseline_n"] + x["window_n"] >= min_n
                ]
                if len(parts) > 1:
                    spread = max(abs(x["contribution"]) for x in parts)
                    subs.append({"dim": dim, "spread": spread, "parts": parts})
            subs.sort(key=lambda d: -d["spread"])
            item["within"] = subs[:2]
        out.append(item)
    return out
