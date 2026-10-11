"""Change detection: is a drop real, and when did it start?

`assess_change` compares the window with a seasonally matched expectation (same weekday in the prior
week(s), scaled for level) and an overdispersed Poisson variance estimated from history, so a weekend dip
or ordinary noise is reported as "within normal variance" rather than a real drop.

`cusum` finds when a series broke from its baseline (one-sided CUSUM on standardized hourly values);
the start estimate is the last time the statistic was at zero before the alarm.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import polars as pl

from engine.analysis.data import FACTOR_DENOM, FACTOR_STEP, Period, segment_mask
from engine.settings import load_config


def daily_counts(sess: pl.DataFrame, step: str, start: datetime, end: datetime) -> pl.DataFrame:
    days = pl.datetime_range(
        start, end - timedelta(days=1), interval="1d", time_zone="UTC", eager=True
    ).alias("day")
    got = (
        sess.filter((pl.col("started_at") >= start) & (pl.col("started_at") < end) & pl.col(step))
        .group_by(pl.col("started_at").dt.truncate("1d").alias("day"))
        .agg(pl.len().alias("n"))
    )
    return pl.DataFrame({"day": days}).join(got, on="day", how="left").fill_null(0).sort("day")


def _dispersion(values: np.ndarray, expected: np.ndarray) -> float:
    """Method-of-moments overdispersion φ in Var = μ(1 + φμ), floored at 0."""
    mask = expected > 0
    if mask.sum() < 3:
        return 0.02
    resid = (values[mask] - expected[mask]) ** 2 - expected[mask]
    phi = float(np.sum(resid) / np.sum(expected[mask] ** 2))
    return max(phi, 0.0)


def assess_change(
    sess: pl.DataFrame, step: str, window: Period, baseline: Period, history_start: datetime
) -> dict[str, Any]:
    """Real change vs normal variance, for a funnel step count (e.g. 'paid')."""
    cfg = load_config("metrics").get("significance", {})
    z_thr, min_rel = float(cfg.get("z_threshold", 2.5)), float(cfg.get("min_relative_change", 0.05))
    # History can't start before the data does (otherwise empty days look like a collapse in prior weeks).
    if sess.height:
        first = sess["started_at"].min()
        first_day = first.replace(hour=0, minute=0, second=0, microsecond=0)
        if first_day > history_start:
            history_start = first_day
    daily = daily_counts(sess, step, history_start, window.end)
    vals = daily["n"].to_numpy().astype(float)
    days = daily["day"].to_list()
    idx = {d: i for i, d in enumerate(days)}

    # Seasonal expectation: each day's same weekday one (or two) weeks earlier, averaged.
    def seasonal(i: int) -> float | None:
        prior = [
            vals[idx[d]] for k in (7, 14) if (d := days[i] - timedelta(days=k)) in idx and d < window.start
        ]
        return float(np.mean(prior)) if prior else None

    win_idx = [i for i, d in enumerate(days) if window.start <= d < window.end]
    hist_idx = [i for i, d in enumerate(days) if d < window.start]
    exp_hist = np.array([seasonal(i) if seasonal(i) is not None else np.nan for i in hist_idx])
    ok = ~np.isnan(exp_hist)
    phi = _dispersion(vals[hist_idx][ok], exp_hist[ok]) if ok.any() else 0.05
    exp_win = [seasonal(i) for i in win_idx]
    seasonal_ok = all(e is not None for e in exp_win)
    if not seasonal_ok:  # not enough history: fall back to the baseline's daily mean
        b = [vals[i] for i, d in enumerate(days) if baseline.start <= d < baseline.end]
        exp_win = [float(np.mean(b)) if b else 0.0] * len(win_idx)
    observed = float(sum(vals[i] for i in win_idx))
    expected = float(sum(exp_win))
    var = sum(e * (1 + phi * e) for e in exp_win) or 1.0
    z = (observed - expected) / math.sqrt(var)
    rel = observed / expected - 1 if expected else 0.0

    naive_b = float(sum(vals[i] for i, d in enumerate(days) if baseline.start <= d < baseline.end))
    naive_rel = (observed / window.days) / (naive_b / baseline.days) - 1 if naive_b else None
    real = abs(z) >= z_thr and abs(rel) >= min_rel
    return {
        "step": step,
        "observed": observed,
        "expected": expected,
        "relative_change": rel,
        "z": z,
        "dispersion": phi,
        "expectation": "same weekday in prior weeks" if seasonal_ok else "baseline daily mean",
        "naive_relative_change_vs_baseline": naive_rel,
        "verdict": ("real_drop" if rel < 0 else "real_rise") if real else "within_normal_variance",
        "daily": [
            {"day": d.isoformat(), "n": int(vals[i]), "expected": seasonal(i)} for i, d in enumerate(days)
        ],
    }


def hourly_series(
    sess: pl.DataFrame, factor: str, start: datetime, end: datetime, segment: dict[str, Any] | None = None
) -> pl.DataFrame:
    s = sess.filter(segment_mask(segment)) if segment else sess
    s = s.filter((pl.col("started_at") >= start) & (pl.col("started_at") < end))
    hours = pl.datetime_range(
        start, end - timedelta(hours=1), interval="1h", time_zone="UTC", eager=True
    ).alias("hour")
    if factor == "traffic":
        got = s.group_by(pl.col("started_at").dt.truncate("1h").alias("hour")).agg(pl.len().alias("num"))
        got = got.with_columns(pl.lit(1).alias("den"))
    else:
        num, den = FACTOR_STEP[factor], FACTOR_DENOM[factor]
        got = (
            s.filter(pl.col(den))
            .group_by(pl.col("started_at").dt.truncate("1h").alias("hour"))
            .agg(pl.len().alias("den"), pl.col(num).sum().alias("num"))
        )
    return pl.DataFrame({"hour": hours}).join(got, on="hour", how="left").fill_null(0).sort("hour")


def cusum(
    sess: pl.DataFrame,
    factor: str,
    baseline: Period,
    window: Period,
    segment: dict[str, Any] | None = None,
    k: float = 0.5,
    h: float = 5.0,
) -> dict[str, Any]:
    """When did the factor (optionally within a segment) drop below its baseline?"""
    base = hourly_series(sess, factor, baseline.start, baseline.end, segment)
    win = hourly_series(sess, factor, window.start, window.end, segment)
    if factor == "traffic":
        # Expected visitors per hour-of-day from the baseline (traffic has a strong daily curve).
        prof = base.group_by(pl.col("hour").dt.hour().alias("hod")).agg(pl.col("num").mean().alias("mu"))
        w = (
            win.with_columns(pl.col("hour").dt.hour().alias("hod"))
            .join(prof, on="hod", how="left")
            .fill_null(0)
        )
        mu = w["mu"].to_numpy()
        x = w["num"].to_numpy().astype(float)
        zt = np.where(mu > 0, (x - mu) / np.sqrt(np.maximum(mu, 1.0)), 0.0)
    else:
        p0 = base["num"].sum() / max(base["den"].sum(), 1)
        n = win["den"].to_numpy().astype(float)
        x = win["num"].to_numpy().astype(float)
        sd = np.sqrt(np.maximum(n * p0 * (1 - p0), 1e-9))
        zt = np.where(n > 0, (x - n * p0) / sd, 0.0)
    s, last_zero, alarm = 0.0, 0, None
    hours = win["hour"].to_list()
    path = []
    for i, z in enumerate(zt):
        s = max(0.0, s - z - k)  # accumulates evidence of a DROP
        path.append(s)
        if s == 0.0:
            last_zero = i + 1
        if s > h and alarm is None:
            alarm = i
            break
    if alarm is None:
        return {"factor": factor, "segment": segment, "detected": False}
    start_i = min(last_zero, len(hours) - 1)
    after = win[start_i:]
    if factor == "traffic":
        mag = None
    else:
        p1 = after["num"].sum() / max(after["den"].sum(), 1)
        mag = {"baseline_rate": p0, "rate_after": p1}
    return {
        "factor": factor,
        "segment": segment,
        "detected": True,
        "changed_at": hours[start_i].isoformat(),
        "alarm_at": hours[alarm].isoformat(),
        "magnitude": mag,
    }
