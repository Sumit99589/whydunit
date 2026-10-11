"""Verification after fixes: has each cause's factor come back within its baseline range?"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl

from engine import db
from engine.analysis.data import FACTOR_DENOM, FACTOR_STEP, segment_mask, session_table
from engine.connectors import registry_for
from engine.connectors.base import Window
from engine.runtime import events as ev
from engine.settings import load_config


def _rate(s: pl.DataFrame, factor: str, segment: dict[str, Any]) -> tuple[int, int]:
    if factor == "traffic":
        return s.filter(segment_mask(segment)).height, s.height  # share of visitors from the segment
    num, den = FACTOR_STEP[factor], FACTOR_DENOM[factor]
    d = s.filter(segment_mask(segment) & pl.col(den))
    return int(d[num].sum()), d.height


def _lower_bound(x: int, n: int, z: float = 1.645) -> float:
    """Wilson lower bound of the baseline rate (90%)."""
    if n == 0:
        return 0.0
    p = x / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


async def verify_case(case_id: str, now: datetime | None = None) -> dict[str, Any]:
    cfg = load_config("watcher")["verify"]
    now = now or datetime.now(UTC)
    case = await db.fetchrow("SELECT * FROM cases WHERE id = %s", (case_id,))
    verdict = await db.fetchrow(
        "SELECT * FROM verdicts WHERE case_id = %s ORDER BY created_at DESC LIMIT 1", (case_id,)
    )
    fixes = {
        f["hypothesis_id"]: f for f in await db.fetch("SELECT * FROM fixes WHERE case_id = %s", (case_id,))
    }
    if not verdict or not verdict["causes"]:
        return {"case": case_id, "skipped": "no causes to verify"}
    applied = [f["applied_at"] for f in fixes.values() if f.get("applied_at")]
    since = min(applied) if applied else now - timedelta(hours=12)
    reg = registry_for(case["world"])
    b_ev = await reg.fetch("funnel_events", Window(case["baseline_start"], case["baseline_end"]), {})
    a_ev = await reg.fetch("funnel_events", Window(since, now), {})
    base, after_all = session_table(b_ev.frame), session_table(a_ev.frame)
    results, all_ok, any_overdue = [], True, False
    for c in verdict["causes"]:
        fix = fixes.get(c["hypothesis_id"])
        start = (fix["applied_at"] if fix and fix.get("applied_at") else since) + timedelta(
            minutes=cfg["settle_minutes"]
        )
        after = after_all.filter(pl.col("started_at") >= start)
        x0, n0 = _rate(base, c["factor"], c["segment"])
        x1, n1 = _rate(after, c["factor"], c["segment"])
        need = cfg["min_visitors"] if c["factor"] == "traffic" else cfg["min_denominator"]
        lo = _lower_bound(x0, n0)
        r0, r1 = (x0 / n0 if n0 else 0.0), (x1 / n1 if n1 else None)
        if n1 < need:
            status = "waiting_for_data"
        elif r1 is not None and r1 >= lo:
            status = "recovered"
        else:
            status = "not_recovered"
        overdue = (
            status != "recovered"
            and fix is not None
            and fix.get("applied_at") is not None
            and now - fix["applied_at"] > timedelta(hours=cfg["deadline_hours"])
        )
        any_overdue |= overdue
        all_ok &= status == "recovered"
        results.append(
            {
                "hypothesis_id": c["hypothesis_id"],
                "statement": c["statement"],
                "factor": c["factor"],
                "segment": c["segment"],
                "baseline_rate": r0,
                "baseline_lower_bound": lo,
                "rate_since_fix": r1,
                "n_since_fix": n1,
                "status": status,
                "overdue": overdue,
                "fix": fix["id"] if fix else None,
            }
        )
        if fix and status == "recovered" and fix["status"] != "recovered":
            await db.execute(
                "UPDATE fixes SET status = 'recovered', verified_at = now() WHERE id = %s", (fix["id"],)
            )
    log_ = await ev.CaseLog(case_id).init()
    await log_.emit("verification", "watcher", checked_at=now.isoformat(), results=results)
    if all_ok:
        await ev.set_status(case_id, "closed", closed_at=now.isoformat())
        await log_.emit(
            "case_closed",
            "watcher",
            summary="Every cause's metric is back within its normal range.",
            results=results,
        )
    elif any_overdue:
        why = "; ".join(
            f"{r['statement']}: {'no data yet' if r['rate_since_fix'] is None else 'still below normal'}"
            for r in results
            if r["status"] != "recovered"
        )
        await ev.set_status(case_id, "verifying", reopened=True)
        await log_.emit(
            "case_reopened", "watcher", reason=f"Not recovered {cfg['deadline_hours']} h after the fix: {why}"
        )
    return {"case": case_id, "closed": all_ok, "results": results}
