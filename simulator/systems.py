"""Clients the simulator uses to touch real systems: the engine's ingest API and Acme's own API."""

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Any

import httpx

from engine import db
from engine.settings import env
from engine.world.model import Journey

log = logging.getLogger("whydunit.sim")

VIEWPORTS = {
    "desktop": ["1440x900", "1536x864", "1920x1080", "1280x800"],
    "mobile": ["390x844", "393x852", "412x915"],
    "tablet": ["820x1180", "1024x1366"],
}


class EngineIngest:
    """Posts events through the real ingest API. Without WHYDUNIT_ENGINE_URL it calls the same FastAPI app
    in-process (same validation and storage path), which keeps local dry runs honest."""

    def __init__(self, base_url: str | None = None, key: str | None = None):
        self.base_url = base_url if base_url is not None else env("WHYDUNIT_ENGINE_URL")
        self.key = key or env("WHYDUNIT_INGEST_KEY")
        if not self.key:
            raise RuntimeError("WHYDUNIT_INGEST_KEY is required")
        transport = None
        if not self.base_url:
            from engine.api.app import create_app

            transport = httpx.ASGITransport(app=create_app())
            self.base_url = "http://engine.local"
        self.client = httpx.AsyncClient(
            base_url=self.base_url, transport=transport, timeout=30, headers={"x-whydunit-key": self.key}
        )

    async def send(self, events: list[dict[str, Any]]) -> int:
        sent = 0
        for i in range(0, len(events), 200):
            batch = events[i : i + 200]
            r = await self.client.post("/ingest/events", json={"events": batch})
            r.raise_for_status()
            sent += r.json()["accepted"]
        return sent

    async def close(self) -> None:
        await self.client.aclose()


def journey_events(j: Journey, rng: random.Random) -> list[dict[str, Any]]:
    viewport = rng.choice(VIEWPORTS[j.device])
    ctx = {
        "browser": j.browser,
        "os": j.os,
        "device": j.device,
        "viewport": viewport,
        "channel": j.channel,
        "utm_source": j.utm_source,
        "utm_medium": j.utm_medium,
        "utm_campaign": j.utm_campaign,
        "country": j.country,
        "synthetic": True,
    }
    if j.channel == "referral":
        ctx["referrer"] = j.utm_source
        ctx["utm_source"] = ctx["utm_medium"] = None
    out = []
    for k, e in enumerate(j.events):
        out.append(
            {
                "event_id": f"{j.session_id}_{k}",
                "name": e.name,
                "ts": e.ts.isoformat(),
                "session_id": j.session_id,
                "anon_id": j.visitor_id,
                "props": e.props,
                "context": {**ctx, "path": e.path},
            }
        )
    return out


class Acme:
    """Acme's public API, exactly as its own pages call it."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or env("ACME_URL")
        self.client = httpx.AsyncClient(
            base_url=self.base_url or "http://acme.invalid",
            timeout=40,
            headers={"user-agent": "whydunit-simulator/1.0"},
        )

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    async def health(self) -> dict[str, Any]:
        r = await self.client.get("/api/health")
        return r.json()

    async def signup(self, name: str, email: str, country: str) -> str:
        r = await self.client.post(
            "/api/signup", json={"name": name, "email": email, "country": country, "synthetic": True}
        )
        r.raise_for_status()
        return r.json()["user_id"]

    async def checkout(self, user_id: str, email: str, pm: str, country: str) -> dict[str, Any]:
        r = await self.client.post(
            "/api/checkout",
            json={
                "user_id": user_id,
                "email": email,
                "payment_method": pm,
                "country": country,
                "synthetic": True,
            },
        )
        if r.status_code >= 500 and r.status_code != 502:
            r.raise_for_status()
        return r.json()

    async def contact(self, name: str, email: str, subject: str, message: str, meta: dict[str, Any]) -> int:
        r = await self.client.post(
            "/api/contact",
            json={
                "name": name,
                "email": email,
                "subject": subject,
                "message": message,
                "synthetic": True,
                "meta": meta,
            },
        )
        r.raise_for_status()
        return r.json()["ticket_id"]

    async def close(self) -> None:
        await self.client.aclose()


async def insert_review(
    created_at: datetime, platform: str, rating: int, title: str, body: str, author: str
) -> None:
    await db.execute(
        "INSERT INTO acme.reviews (created_at, platform, rating, title, body, author, synthetic) "
        "VALUES (%s,%s,%s,%s,%s,%s,true)",
        (created_at, platform, rating, title, body, author),
    )


async def insert_ticket_direct(
    created_at: datetime, name: str, email: str, subject: str, body: str, meta: dict[str, Any]
) -> None:
    """Used only when Acme is not reachable (local dry runs)."""
    await db.execute(
        "INSERT INTO acme.helpdesk_tickets (created_at, email, name, subject, body, meta, synthetic) "
        "VALUES (%s,%s,%s,%s,%s,%s,true)",
        (created_at, email, name, subject, body, db.jsonb(meta)),
    )
