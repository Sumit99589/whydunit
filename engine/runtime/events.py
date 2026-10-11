"""Append-only case event log (Postgres `case_events`), streamed to the UI over SSE.

Every step of an investigation is an event: detective started, tool call, evidence pinned, finding,
question, answer, attribution, verdict, fix, verification. Replay mode re-emits the stored log with its
original timing (optionally sped up).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from engine import db
from engine.runtime.schemas import Case, Finding, Hypothesis


class CaseLog:
    def __init__(self, case_id: str):
        self.case_id = case_id
        self._seq = 0
        self._lock = asyncio.Lock()

    async def init(self) -> CaseLog:
        row = await db.fetchrow(
            "SELECT COALESCE(MAX(seq), 0) AS s FROM case_events WHERE case_id = %s", (self.case_id,)
        )
        self._seq = int(row["s"])
        return self

    async def emit(self, type: str, actor: str | None = None, **payload: Any) -> int:
        async with self._lock:
            self._seq += 1
            seq = self._seq
            await db.execute(
                "INSERT INTO case_events (case_id, seq, type, actor, payload) VALUES (%s, %s, %s, %s, %s)",
                (self.case_id, seq, type, actor, db.jsonb(payload)),
            )
        return seq


async def save_case(case: Case) -> None:
    await db.execute(
        """INSERT INTO cases (id, project_id, world, metric, question, window_start, window_end, baseline_start,
               baseline_end, status, auto_opened)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, updated_at = now()""",
        (
            case.id,
            case.project_id,
            case.world,
            case.metric,
            case.question,
            case.window_start,
            case.window_end,
            case.baseline_start,
            case.baseline_end,
            case.status,
            case.auto_opened,
        ),
    )


async def set_status(case_id: str, status: str, **summary: Any) -> None:
    if summary:
        await db.execute(
            "UPDATE cases SET status = %s, summary = summary || %s, updated_at = now() WHERE id = %s",
            (status, db.jsonb(summary), case_id),
        )
    else:
        await db.execute("UPDATE cases SET status = %s, updated_at = now() WHERE id = %s", (status, case_id))


async def add_cost(case_id: str, cost: float) -> None:
    await db.execute(
        "UPDATE cases SET cost_usd = cost_usd + %s, updated_at = now() WHERE id = %s", (cost, case_id)
    )


async def save_evidence(case_id: str, bundle: Any, detective: str | None) -> None:
    await db.execute(
        """INSERT INTO evidence (id, case_id, kind, connector, tier, detective, query, window_start, window_end,
               data_ref, summary, artifacts, confidence)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (case_id, id) DO NOTHING""",
        (
            bundle.id,
            case_id,
            bundle.kind,
            bundle.connector,
            bundle.tier,
            detective,
            db.jsonb(bundle.query),
            bundle.window["start"] if bundle.window else None,
            bundle.window["end"] if bundle.window else None,
            db.jsonb(
                {
                    **bundle.data_ref,
                    "row_count": bundle.row_count,
                    "sample": bundle.sample,
                    "notes": bundle.notes,
                }
            ),
            bundle.summary,
            db.jsonb([a.model_dump() for a in bundle.artifacts]),
            bundle.confidence,
        ),
    )


async def save_finding(case_id: str, f: Finding) -> None:
    await db.execute(
        """INSERT INTO findings (id, case_id, detective, claim, kind, evidence_ids, metrics_refs, confidence, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status,
             confidence = EXCLUDED.confidence""",
        (
            f.id,
            case_id,
            f.detective,
            f.claim,
            f.kind,
            f.evidence_ids,
            db.jsonb(f.metrics_refs),
            f.confidence,
            f.status,
        ),
    )


async def save_hypothesis(case_id: str, h: Hypothesis) -> None:
    await db.execute(
        """INSERT INTO hypotheses (id, case_id, statement, effect, supporting, contradicting, status, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status,
             supporting = EXCLUDED.supporting, contradicting = EXCLUDED.contradicting""",
        (
            h.id,
            case_id,
            h.statement,
            db.jsonb(h.effect.model_dump(mode="json")),
            h.supporting,
            h.contradicting,
            h.status,
            h.proposed_by,
        ),
    )


async def save_llm_call(rec: Any) -> None:
    await db.execute(
        """INSERT INTO llm_calls (case_id, role, model, prompt_tokens, completion_tokens, cost_usd, latency_s, cached, tag)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            rec.case_id,
            rec.role,
            rec.model,
            rec.prompt_tokens,
            rec.completion_tokens,
            rec.cost_usd,
            rec.latency_s,
            rec.cached,
            rec.tag,
        ),
    )
    if rec.case_id and rec.cost_usd:
        await add_cost(rec.case_id, rec.cost_usd)


def _event_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": r["seq"],
        "ts": r["ts"].isoformat(),
        "type": r["type"],
        "actor": r["actor"],
        "payload": r["payload"],
    }


async def events_since(case_id: str, after_seq: int = 0, limit: int = 500) -> list[dict[str, Any]]:
    rows = await db.fetch(
        "SELECT seq, ts, type, actor, payload FROM case_events WHERE case_id = %s AND seq > %s "
        "ORDER BY seq LIMIT %s",
        (case_id, after_seq, limit),
    )
    return [_event_row(r) for r in rows]


TERMINAL = {"case_closed", "case_failed", "investigation_complete"}


async def stream(
    case_id: str, after_seq: int = 0, *, poll_s: float = 0.4, idle_timeout_s: float = 900, follow: bool = True
) -> AsyncIterator[dict[str, Any]]:
    """Yield events as they are appended (polling, so it works across processes)."""
    last, idle = after_seq, 0.0
    while True:
        batch = await events_since(case_id, last)
        for ev in batch:
            last = ev["seq"]
            yield ev
        if batch:
            idle = 0.0
            if not follow and batch[-1]["type"] in TERMINAL:
                return
        else:
            if not follow:
                return
            idle += poll_s
            if int(idle / poll_s) % int(15 / poll_s) == 0:
                yield {"heartbeat": True}
            if idle >= idle_timeout_s:
                return
            await asyncio.sleep(poll_s)


async def replay(case_id: str, speed: float = 1.0, max_gap_s: float = 4.0) -> AsyncIterator[dict[str, Any]]:
    """Re-emit the stored log with its original rhythm (gaps capped so dead time doesn't drag)."""
    events = await events_since(case_id, 0, limit=100_000)
    prev: datetime | None = None
    for ev in events:
        ts = datetime.fromisoformat(ev["ts"])
        if prev is not None:
            gap = min((ts - prev).total_seconds() / max(speed, 0.01), max_gap_s)
            if gap > 0:
                await asyncio.sleep(gap)
        prev = ts
        yield {**ev, "replay": True}


def sse(ev: dict[str, Any]) -> str:
    return f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"
