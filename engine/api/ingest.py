"""Ingest API: batched funnel events and chunked rrweb recordings from the snippet (and the simulator)."""

from __future__ import annotations

import gzip
import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from engine import db
from engine.projects import project_for_key
from engine.storage import get_blob_store

router = APIRouter(prefix="/ingest", tags=["ingest"])

MAX_EVENTS_PER_BATCH = 200
MAX_REPLAY_BYTES = 8 * 1024 * 1024
COUNTRY_HEADERS = ("x-whydunit-country", "x-vercel-ip-country", "cf-ipcountry")
PAID_MEDIUMS = {"cpc", "ppc", "paid", "paid_search", "paidsearch", "display", "paid_social"}


class EventContext(BaseModel):
    browser: str | None = None
    os: str | None = None
    device: str | None = None
    viewport: str | None = None
    path: str | None = None
    referrer: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    channel: str | None = None
    country: str | None = None
    synthetic: bool = False


class EventIn(BaseModel):
    event_id: str = Field(min_length=6, max_length=80)
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    ts: datetime
    session_id: str = Field(min_length=6, max_length=80)
    anon_id: str | None = Field(default=None, max_length=80)
    user_id: str | None = Field(default=None, max_length=120)
    props: dict[str, Any] = Field(default_factory=dict)
    context: EventContext = Field(default_factory=EventContext)


class EventBatch(BaseModel):
    key: str | None = None
    events: list[EventIn] = Field(max_length=MAX_EVENTS_PER_BATCH)


class ReplayChunk(BaseModel):
    key: str | None = None
    session_id: str = Field(min_length=6, max_length=80)
    chunk_index: int = Field(ge=0, le=10_000)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    events: list[dict[str, Any]]


class RateLimiter:
    """Token bucket per (project, client)."""

    def __init__(self, rate_per_s: float = 10.0, burst: int = 60):
        self.rate, self.burst = rate_per_s, burst
        self.buckets: dict[tuple[str, str], tuple[float, float]] = defaultdict(
            lambda: (float(burst), time.monotonic())
        )

    def allow(self, project: str, client: str) -> bool:
        tokens, last = self.buckets[(project, client)]
        now = time.monotonic()
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        if tokens < 1:
            self.buckets[(project, client)] = (tokens, now)
            return False
        self.buckets[(project, client)] = (tokens - 1, now)
        return True


limiter = RateLimiter()


def derive_channel(ctx: EventContext) -> str:
    if ctx.channel:
        return ctx.channel
    medium = (ctx.utm_medium or "").lower()
    if medium in PAID_MEDIUMS:
        return "paid"
    if ctx.utm_source or (ctx.referrer and medium != "organic"):
        return "referral"
    return "organic"


def client_id(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def header_country(request: Request) -> str | None:
    for h in COUNTRY_HEADERS:
        v = request.headers.get(h)
        if v and len(v) == 2 and v.upper() != "XX":
            return v.upper()
    return None


async def _read_json(request: Request, limit: int) -> Any:
    body = await request.body()
    if request.headers.get("content-encoding", "").lower() == "gzip":
        body = gzip.decompress(body)
    if len(body) > limit:
        raise HTTPException(413, "payload too large")
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(400, "invalid JSON") from e


async def _authenticate(request: Request, body_key: str | None) -> str:
    key = request.headers.get("x-whydunit-key") or request.query_params.get("key") or body_key
    if not key:
        raise HTTPException(401, "missing project key")
    project = await project_for_key(key)
    if not project:
        raise HTTPException(401, "unknown project key")
    if not limiter.allow(project, client_id(request)):
        raise HTTPException(429, "rate limited")
    return project


@router.post("/events")
async def ingest_events(request: Request) -> dict[str, Any]:
    raw = await _read_json(request, 1024 * 1024)
    try:
        batch = EventBatch.model_validate(raw)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)) from e
    project = await _authenticate(request, batch.key)
    hdr_country = header_country(request)

    event_rows, sessions = [], {}
    for ev in batch.events:
        ctx = ev.context
        # Simulator traffic carries its simulated country; real traffic uses the edge's geo header.
        body_country = ctx.country.upper() if ctx.country else None
        country = (body_country or hdr_country) if ctx.synthetic else (hdr_country or body_country)
        channel = derive_channel(ctx)
        ts = ev.ts if ev.ts.tzinfo else ev.ts.replace(tzinfo=UTC)
        event_rows.append(
            (
                ev.event_id,
                project,
                ev.name,
                ts,
                ev.session_id,
                ev.anon_id,
                ev.user_id,
                ctx.path,
                ctx.browser,
                ctx.os,
                ctx.device,
                ctx.viewport,
                country,
                channel,
                db.jsonb(ev.props),
                ctx.synthetic,
            )
        )
        s = sessions.setdefault(
            ev.session_id,
            {
                "started_at": ts,
                "last_seen_at": ts,
                "ev": ev,
                "country": country,
                "channel": channel,
                "user_id": None,
            },
        )
        if ts < s["started_at"]:
            s.update(started_at=ts, ev=ev, country=country, channel=channel)
        s["last_seen_at"] = max(s["last_seen_at"], ts)
        s["user_id"] = ev.user_id or s["user_id"]

    async with db.connection() as conn, conn.transaction():
        for sid, s in sessions.items():
            ev, ctx = s["ev"], s["ev"].context
            await conn.execute(
                """INSERT INTO sessions (id, project_id, anon_id, user_id, started_at, last_seen_at, browser, os,
                       device, viewport, country, channel, utm_source, utm_medium, utm_campaign, landing_path, synthetic)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET
                       started_at = LEAST(sessions.started_at, EXCLUDED.started_at),
                       last_seen_at = GREATEST(sessions.last_seen_at, EXCLUDED.last_seen_at),
                       user_id = COALESCE(EXCLUDED.user_id, sessions.user_id)""",
                (
                    sid,
                    project,
                    ev.anon_id,
                    s["user_id"],
                    s["started_at"],
                    s["last_seen_at"],
                    ctx.browser,
                    ctx.os,
                    ctx.device,
                    ctx.viewport,
                    s["country"],
                    s["channel"],
                    ctx.utm_source,
                    ctx.utm_medium,
                    ctx.utm_campaign,
                    ctx.path,
                    ctx.synthetic,
                ),
            )
        cur = conn.cursor()
        await cur.executemany(
            """INSERT INTO events (event_id, project_id, name, ts, session_id, anon_id, user_id, path, browser, os,
                   device, viewport, country, channel, props, synthetic)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (project_id, event_id) DO NOTHING""",
            event_rows,
        )
    return {"accepted": len(event_rows), "project": project}


@router.post("/replay")
async def ingest_replay(request: Request) -> dict[str, Any]:
    raw = await _read_json(request, MAX_REPLAY_BYTES)
    try:
        chunk = ReplayChunk.model_validate(raw)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)) from e
    project = await _authenticate(request, chunk.key)
    if not chunk.events:
        raise HTTPException(422, "empty chunk")

    started = chunk.started_at or _rrweb_ts(chunk.events[0])
    ended = chunk.ended_at or _rrweb_ts(chunk.events[-1])
    day = (started or datetime.now(UTC)).strftime("%Y-%m-%d")
    key = f"replays/{project}/{day}/{chunk.session_id}/{chunk.chunk_index:05d}.json.gz"
    blob = gzip.compress(json.dumps(chunk.events, separators=(",", ":")).encode())
    await get_blob_store().put(key, blob, "application/gzip")

    replay_id = f"{chunk.session_id}:{chunk.chunk_index}"
    async with db.connection() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO replays (id, project_id, session_id, chunk_index, started_at, ended_at, blob_key,
                   size_bytes, event_count)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (session_id, chunk_index) DO UPDATE SET blob_key = EXCLUDED.blob_key,
                   size_bytes = EXCLUDED.size_bytes, event_count = EXCLUDED.event_count,
                   ended_at = EXCLUDED.ended_at""",
            (
                replay_id,
                project,
                chunk.session_id,
                chunk.chunk_index,
                started,
                ended,
                key,
                len(blob),
                len(chunk.events),
            ),
        )
        await conn.execute("UPDATE sessions SET has_replay = true WHERE id = %s", (chunk.session_id,))
    return {"stored": key, "events": len(chunk.events), "bytes": len(blob)}


def _rrweb_ts(event: dict[str, Any]) -> datetime | None:
    ts = event.get("timestamp")
    if isinstance(ts, int | float):
        return datetime.fromtimestamp(ts / 1000, tz=UTC)
    return None
