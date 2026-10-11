"""Session-level funnel table built from funnel events: the common input to every analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import polars as pl

STEPS = ("visited", "signed_up", "checkout", "paid")
FACTORS = ("traffic", "signup_rate", "checkout_rate", "payment_success_rate")
FACTOR_STEP = {
    "traffic": "visited",
    "signup_rate": "signed_up",
    "checkout_rate": "checkout",
    "payment_success_rate": "paid",
}
FACTOR_DENOM = {"signup_rate": "visited", "checkout_rate": "signed_up", "payment_success_rate": "checkout"}
DIMS = ("engine", "browser", "os", "device", "country", "channel")


def engine_expr() -> pl.Expr:
    """Rendering engine: every browser on iOS/iPadOS is WebKit, as is Safari everywhere."""
    return (
        pl.when(pl.col("os").is_in(["iOS", "iPadOS"]) | (pl.col("browser") == "Safari"))
        .then(pl.lit("webkit"))
        .when(pl.col("browser") == "Firefox")
        .then(pl.lit("firefox"))
        .otherwise(pl.lit("chromium"))
    )


def session_table(events: pl.DataFrame) -> pl.DataFrame:
    """One row per session: start time, segment dims, monotone funnel flags and raw event flags."""
    if events.height == 0:
        return pl.DataFrame(
            schema={
                "session_id": pl.Utf8,
                "started_at": pl.Datetime("us", "UTC"),
                **{d: pl.Utf8 for d in DIMS},
                **{s: pl.Boolean for s in STEPS},
            }
        )
    ev = events.with_columns(pl.col("ts").dt.convert_time_zone("UTC"))
    agg = ev.group_by("session_id").agg(
        pl.col("ts").min().alias("started_at"),
        *[pl.col(c).drop_nulls().first().alias(c) for c in ("browser", "os", "device", "country", "channel")],
        (pl.col("name") == "signup_started").any().alias("raw_signup_started"),
        (pl.col("name") == "signup_completed").any().alias("raw_signup_completed"),
        (pl.col("name") == "checkout_started").any().alias("raw_checkout_started"),
        (pl.col("name") == "payment_succeeded").any().alias("raw_payment_succeeded"),
        (pl.col("name") == "payment_failed").any().alias("raw_payment_failed"),
    )
    return agg.with_columns(
        engine_expr().alias("engine"),
        pl.lit(True).alias("visited"),
        (
            pl.col("raw_signup_completed")
            | pl.col("raw_checkout_started")
            | pl.col("raw_payment_succeeded")
            | pl.col("raw_payment_failed")
        ).alias("signed_up"),
        (
            pl.col("raw_checkout_started") | pl.col("raw_payment_succeeded") | pl.col("raw_payment_failed")
        ).alias("checkout"),
        pl.col("raw_payment_succeeded").alias("paid"),
    ).sort("started_at")


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime

    @property
    def days(self) -> float:
        return (self.end - self.start).total_seconds() / 86400

    def filter(self, sess: pl.DataFrame, col: str = "started_at") -> pl.DataFrame:
        return sess.filter((pl.col(col) >= self.start) & (pl.col(col) < self.end))

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def segment_mask(segment: dict[str, object] | None) -> pl.Expr:
    expr = pl.lit(True)
    for dim, val in (segment or {}).items():
        vals = list(val) if isinstance(val, list | tuple | set) else [val]
        expr = expr & pl.col(dim).is_in(vals)
    return expr


def funnel_counts(sess: pl.DataFrame) -> dict[str, int]:
    return {s: int(sess[s].sum()) if sess.height else 0 for s in STEPS}
