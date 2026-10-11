"""The always-on watcher: opens a case by itself when the headline metric drops, and verifies open cases.

uv run whydunit watch            # one pass (the scheduled job runs this every 30 minutes)
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import polars as pl

from engine import db
from engine.analysis.data import session_table
from engine.connectors import registry_for
from engine.connectors.base import Window
from engine.runtime.verify import verify_case
from engine.settings import env, load_config

log = logging.getLogger("whydunit.watcher")


def rolling_drop(sess: pl.DataFrame, now: datetime, hours: float, phi: float = 0.006) -> dict[str, Any]:
    """Paid subs in the last `hours` vs the same hours one and two weeks earlier (overdispersed Poisson)."""

    def count(end: datetime) -> int:
        return sess.filter(
            (pl.col("started_at") >= end - timedelta(hours=hours))
            & (pl.col("started_at") < end)
            & pl.col("paid")
        ).height

    obs = count(now)
    prior = [count(now - timedelta(days=7 * k)) for k in (1, 2)]
    prior = [p for p in prior if p > 0] or [0]
    exp = sum(prior) / len(prior)
    var = exp * (1 + phi * exp) or 1.0
    return {
        "observed": obs,
        "expected": exp,
        "z": (obs - exp) / math.sqrt(var),
        "relative": (obs / exp - 1) if exp else 0.0,
    }


async def detect(world: str = "live", now: datetime | None = None) -> dict[str, Any] | None:
    cfg = load_config("watcher")["detect"]
    now = now or datetime.now(UTC)
    reg = registry_for(world)
    b = await reg.fetch(
        "funnel_events", Window(now - timedelta(days=15), now), {"names": ["payment_succeeded", "page_view"]}
    )
    sess = session_table(b.frame)
    persist = cfg["persist_hours"]
    checks = [
        rolling_drop(sess, now - timedelta(hours=h), cfg["lookback_hours"], cfg.get("dispersion", 0.006))
        for h in (0, persist / 2, persist)
    ]
    sustained = all(c["relative"] <= -cfg["min_drop"] and c["z"] <= -cfg["z_threshold"] for c in checks)
    return {"now": now.isoformat(), "checks": checks, "sustained_drop": sustained}


async def notify(text: str) -> None:
    url = env("WATCHER_WEBHOOK_URL")
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(url, json={"text": text})
    except Exception as e:  # noqa: BLE001
        log.warning("webhook failed: %s", e)


async def watch_once(
    world: str = "live", now: datetime | None = None, *, investigate: bool = True
) -> dict[str, Any]:
    from engine.agents import fixer
    from engine.runtime.orchestrator import investigate as run_case

    now = now or datetime.now(UTC)
    out: dict[str, Any] = {"opened": None, "verified": []}
    for c in await db.fetch(
        "SELECT id FROM cases WHERE world = %s AND status IN ('verifying', 'fixing') "
        "AND id IN (SELECT case_id FROM fixes WHERE applied_at IS NOT NULL)",
        (world,),
    ):
        out["verified"].append(await verify_case(c["id"], now))
    open_case = await db.fetchrow(
        "SELECT id FROM cases WHERE world = %s AND status <> 'closed' AND status <> 'failed' "
        "AND created_at > %s",
        (world, now - timedelta(days=3)),
    )
    if open_case:
        out["skipped_detection"] = f"case {open_case['id']} is still open"
        return out
    d = await detect(world, now)
    out["detection"] = d
    if not d or not d["sustained_drop"] or not investigate:
        return out
    cfg = load_config("watcher")["detect"]
    w0 = (now - timedelta(days=cfg["window_days"])).replace(minute=0, second=0, microsecond=0)
    w1 = now.replace(minute=0, second=0, microsecond=0)
    window = {
        "window_start": w0,
        "window_end": w1,
        "baseline_start": w0 - timedelta(days=7),
        "baseline_end": w1 - timedelta(days=7),
    }
    res = await run_case(world, "paid_subs", auto_opened=True, window=window)
    case = res["case"]
    out["opened"] = case.id
    verdict = res.get("verdict")
    if verdict and verdict["kind"] == "causes":
        await fixer.propose(case.id, world, verdict)
    ui = env("WHYDUNIT_UI_URL", "")
    rel = d["checks"][0]["relative"]
    await notify(
        f"Whydunit opened a case: paid subscriptions are down {abs(rel) * 100:.0f}% on the same hours last week. "
        + (f"Verdict: {verdict['narrative'][:300]} " if verdict else "")
        + f"{ui}/cases/{case.id}"
    )
    return out
