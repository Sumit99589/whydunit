"""Shared helpers for connectors."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import polars as pl

from engine.connectors.base import KIND_SCHEMAS, Window


def frame(rows: list[dict[str, Any]], kind: str) -> pl.DataFrame:
    """Rows -> DataFrame with at least the kind's schema columns (empty-safe)."""
    if not rows:
        return pl.DataFrame({c: [] for c in KIND_SCHEMAS[kind]})
    df = pl.DataFrame(rows, infer_schema_length=None)
    for c in KIND_SCHEMAS[kind]:
        if c not in df.columns:
            df = df.with_columns(pl.lit(None).alias(c))
    return df


def fmt_window(w: Window | None) -> str:
    if not w:
        return "all time"
    return f"{_d(w.start)} → {_d(w.end)}"


def _d(t: datetime) -> str:
    return t.strftime("%a %b %d %H:%M UTC")


def top_counts(values: list[Any], n: int = 5) -> str:
    c = Counter(v for v in values if v is not None)
    return ", ".join(f"{k} {v:,}" for k, v in c.most_common(n))


def segment_filters(filters: dict[str, Any], allowed: set[str]) -> tuple[str, list[Any]]:
    """{'browser': 'Safari', 'country': ['BR','AR']} -> ' AND browser = %s AND country = ANY(%s)', params."""
    sql, params = "", []
    for k, v in (filters.get("segment") or {}).items():
        if k not in allowed:
            raise ValueError(f"cannot filter on {k!r}")
        if isinstance(v, list | tuple):
            sql += f" AND {k} = ANY(%s)"
            params.append(list(v))
        else:
            sql += f" AND {k} = %s"
            params.append(v)
    return sql, params
