"""Cases API: open a case, read its state, and stream its event log (live or replay) over SSE."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from engine import db
from engine.runtime import events as ev

router = APIRouter(prefix="/cases", tags=["cases"])
log = logging.getLogger("whydunit.api.cases")
_tasks: set[asyncio.Task] = set()


class OpenCase(BaseModel):
    world: str = "fixture:3inc"
    metric: str = "paid_subs"
    detectives: list[str] | None = None
    with_lead: bool = True


@router.post("")
async def open_case(body: OpenCase) -> dict[str, Any]:
    from engine.runtime import orchestrator

    if not (body.world == "live" or body.world.startswith("fixture:")):
        raise HTTPException(422, "world must be 'live' or 'fixture:<name>'")
    case, registry = await orchestrator.open_case(body.world, body.metric)

    async def run() -> None:
        try:
            ctx, reports = await orchestrator.run_detectives(case, registry, body.detectives)
            verdict = None
            if body.with_lead:
                try:
                    from engine.agents.lead import LeadDetective

                    verdict = await LeadDetective(ctx, reports).run()
                except ImportError:
                    pass
            await ev.set_status(case.id, "verdict" if verdict else "investigating", cost=ctx.meter.summary())
            await ctx.log.emit("investigation_complete", "whydunit", cost=ctx.meter.summary())
        except Exception as e:  # noqa: BLE001
            log.exception("case %s failed", case.id)
            await ev.set_status(case.id, "failed", error=str(e)[:300])
            log_ = await ev.CaseLog(case.id).init()
            await log_.emit("case_failed", "whydunit", error=f"{type(e).__name__}: {e}"[:300])

    t = asyncio.create_task(run())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return {"id": case.id, "stream": f"/cases/{case.id}/stream"}


async def resolve(case_id: str) -> str:
    """`flagship` → FLAGSHIP_CASE_ID, else the newest finished case (live first, then the 3-incident fixture)."""
    if case_id != "flagship":
        return case_id
    from engine.settings import env

    if env("FLAGSHIP_CASE_ID"):
        return env("FLAGSHIP_CASE_ID")  # type: ignore[return-value]
    row = await db.fetchrow(
        "SELECT id FROM cases WHERE status IN ('closed', 'verdict', 'verifying', 'fixing') AND world IN ('live', 'fixture:3inc') "
        "ORDER BY (world = 'live') DESC, (status = 'closed') DESC, created_at DESC LIMIT 1"
    )
    if not row:
        raise HTTPException(404, "no flagship case yet")
    return row["id"]


@router.get("")
async def list_cases(limit: int = 50) -> list[dict[str, Any]]:
    rows = await db.fetch(
        "SELECT id, world, metric, question, status, auto_opened, cost_usd, window_start, window_end, created_at "
        "FROM cases ORDER BY created_at DESC LIMIT %s",
        (min(limit, 200),),
    )
    return rows


@router.get("/{case_id}")
async def get_case(case_id: str) -> dict[str, Any]:
    case_id = await resolve(case_id)
    case = await db.fetchrow("SELECT * FROM cases WHERE id = %s", (case_id,))
    if not case:
        raise HTTPException(404, "no such case")
    return {
        "case": case,
        "evidence": await db.fetch(
            "SELECT * FROM evidence WHERE case_id = %s ORDER BY fetched_at", (case_id,)
        ),
        "findings": await db.fetch(
            "SELECT * FROM findings WHERE case_id = %s ORDER BY created_at", (case_id,)
        ),
        "hypotheses": await db.fetch(
            "SELECT * FROM hypotheses WHERE case_id = %s ORDER BY created_at", (case_id,)
        ),
        "verdicts": await db.fetch(
            "SELECT * FROM verdicts WHERE case_id = %s ORDER BY created_at", (case_id,)
        ),
        "fixes": await db.fetch("SELECT * FROM fixes WHERE case_id = %s ORDER BY created_at", (case_id,)),
    }


_series_cache: dict[str, dict[str, Any]] = {}


@router.get("/{case_id}/series")
async def series(case_id: str) -> dict[str, Any]:
    case_id = await resolve(case_id)
    """Hourly and daily paid subscriptions (and visitors) for the case's history, plus chart annotations."""
    if case_id in _series_cache:
        return _series_cache[case_id]
    from datetime import timedelta

    import polars as pl

    from engine.analysis.data import session_table
    from engine.connectors import registry_for
    from engine.connectors.base import Window

    case = await db.fetchrow("SELECT * FROM cases WHERE id = %s", (case_id,))
    if not case:
        raise HTTPException(404, "no such case")
    reg = registry_for(case["world"])
    start = min(case["baseline_start"], case["window_start"] - timedelta(days=7))
    b = await reg.fetch("funnel_events", Window(start, case["window_end"]), {})
    sess = session_table(b.frame)
    daily = (
        sess.group_by(pl.col("started_at").dt.truncate("1d").alias("t"))
        .agg(
            pl.col("paid").sum().alias("paid"),
            pl.len().alias("visitors"),
            pl.col("signed_up").sum().alias("signups"),
        )
        .sort("t")
    )
    hourly = (
        sess.group_by(pl.col("started_at").dt.truncate("6h").alias("t"))
        .agg(pl.col("paid").sum().alias("paid"), pl.len().alias("visitors"))
        .sort("t")
    )
    marks = []
    for h in await db.fetch(
        "SELECT statement, effect, status, created_by FROM hypotheses WHERE case_id = %s", (case_id,)
    ):
        if h["effect"].get("start"):
            marks.append(
                {
                    "t": h["effect"]["start"],
                    "label": h["statement"],
                    "kind": h["created_by"],
                    "status": h["status"],
                }
            )
    out = {
        "window": {"start": case["window_start"].isoformat(), "end": case["window_end"].isoformat()},
        "baseline": {"start": case["baseline_start"].isoformat(), "end": case["baseline_end"].isoformat()},
        "daily": [
            {"t": r["t"].isoformat(), **{k: int(r[k]) for k in ("paid", "visitors", "signups")}}
            for r in daily.to_dicts()
        ],
        "six_hourly": [
            {"t": r["t"].isoformat(), "paid": int(r["paid"]), "visitors": int(r["visitors"])}
            for r in hourly.to_dicts()
        ],
        "annotations": marks,
    }
    if case["status"] in ("verdict", "closed"):
        _series_cache[case_id] = out
    return out


@router.get("/{case_id}/events")
async def get_events(case_id: str, after: int = 0) -> list[dict[str, Any]]:
    case_id = await resolve(case_id)
    return await ev.events_since(case_id, after, limit=5000)


@router.get("/{case_id}/stream")
async def stream(
    case_id: str, request: Request, replay: bool = False, speed: float = 1.0, after: int = 0
) -> StreamingResponse:
    case_id = await resolve(case_id)
    if not await db.fetchrow("SELECT 1 FROM cases WHERE id = %s", (case_id,)):
        raise HTTPException(404, "no such case")
    last = int(request.headers.get("last-event-id") or after or 0)

    async def gen():
        yield "retry: 2000\n\n"
        source = ev.replay(case_id, speed=speed) if replay else ev.stream(case_id, last, follow=True)
        async for e in source:
            if await request.is_disconnected():
                break
            yield ev.sse(e)
            if e["type"] in ev.TERMINAL and replay is False and e["type"] != "investigation_complete":
                break
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
