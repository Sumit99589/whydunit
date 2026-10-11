"""Simulator state in Postgres (schema `sim`), so ticks running in GitHub Actions share it."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from engine import db


async def get(key: str, default: Any = None) -> Any:
    row = await db.fetchrow("SELECT value FROM sim.state WHERE key = %s", (key,))
    return row["value"] if row else default


async def put(key: str, value: Any) -> None:
    await db.execute(
        "INSERT INTO sim.state (key, value, updated_at) VALUES (%s, %s, now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (key, db.jsonb(value)),
    )


async def get_time(key: str) -> datetime | None:
    v = await get(key)
    return datetime.fromisoformat(v) if v else None


async def record_health(results: dict[str, dict[str, Any]], deployment_url: str | None) -> None:
    for probe, r in results.items():
        await db.execute(
            "INSERT INTO sim.health (probe, ok, deployment_url, detail) VALUES (%s, %s, %s, %s)",
            (probe, bool(r["ok"]), deployment_url, db.jsonb(r)),
        )


async def last_health() -> dict[str, bool]:
    rows = await db.fetch("SELECT DISTINCT ON (probe) probe, ok FROM sim.health ORDER BY probe, ts DESC")
    return {r["probe"]: r["ok"] for r in rows}
