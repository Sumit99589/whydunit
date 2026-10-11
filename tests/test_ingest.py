import gzip
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from engine.api import ingest
from engine.api.app import create_app
from engine.projects import create_project
from engine.storage import LocalBlobStore, set_blob_store


@pytest.fixture
async def client(pg, tmp_path):
    store = LocalBlobStore(tmp_path)
    set_blob_store(store)
    ingest.limiter.buckets.clear()
    key = await create_project("t_" + uuid.uuid4().hex[:8], "Test")
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        c.headers["x-whydunit-key"] = key
        c.store = store
        yield c
    set_blob_store(None)


def event(name, session, ts, **ctx):
    return {
        "event_id": uuid.uuid4().hex,
        "name": name,
        "ts": ts.isoformat(),
        "session_id": session,
        "anon_id": "anon_" + session,
        "props": {"plan": "pro"},
        "context": ctx,
    }


async def test_events_create_session_and_rows(client, pg):
    sid = "s_" + uuid.uuid4().hex[:10]
    t0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
    batch = {
        "events": [
            event(
                "signup_started", sid, t0 + timedelta(seconds=30), browser="Safari", os="iOS", device="mobile"
            ),
            event(
                "page_view",
                sid,
                t0,
                browser="Safari",
                os="iOS",
                device="mobile",
                path="/",
                utm_source="google",
                utm_medium="cpc",
            ),
        ]
    }
    r = await client.post("/ingest/events", json=batch, headers={"x-vercel-ip-country": "gb"})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 2
    # idempotent on event_id
    r = await client.post("/ingest/events", json=batch)
    assert r.status_code == 200
    rows = await pg.fetch(
        "SELECT name, country, channel FROM events WHERE session_id = %s ORDER BY ts", (sid,)
    )
    assert [r["name"] for r in rows] == ["page_view", "signup_started"]
    assert {r["country"] for r in rows} == {"GB"}
    s = await pg.fetchrow("SELECT * FROM sessions WHERE id = %s", (sid,))
    assert s["started_at"] == t0 and s["channel"] == "paid" and s["landing_path"] == "/"


async def test_simulator_country_and_synthetic(client, pg):
    sid = "s_" + uuid.uuid4().hex[:10]
    r = await client.post(
        "/ingest/events",
        json={"events": [event("page_view", sid, datetime.now(UTC), country="de", synthetic=True)]},
    )
    assert r.status_code == 200
    row = await pg.fetchrow("SELECT country, synthetic, channel FROM events WHERE session_id = %s", (sid,))
    assert row == {"country": "DE", "synthetic": True, "channel": "organic"}


async def test_auth_and_validation(client):
    r = await client.post("/ingest/events", json={"events": []}, headers={"x-whydunit-key": "nope"})
    assert r.status_code == 401
    r = await client.post("/ingest/events", json={"events": [{"name": "Bad Name"}]})
    assert r.status_code == 422


async def test_rate_limit(client):
    ingest.limiter.burst = 3
    ingest.limiter.buckets.clear()
    try:
        codes = [(await client.post("/ingest/events", json={"events": []})).status_code for _ in range(5)]
    finally:
        ingest.limiter.burst = 60
    assert codes[:3] == [200, 200, 200] and 429 in codes[3:]


async def test_replay_chunk_gzip(client, pg):
    sid = "s_" + uuid.uuid4().hex[:10]
    ts = int(datetime(2026, 10, 6, 9, 0, tzinfo=UTC).timestamp() * 1000)
    await client.post("/ingest/events", json={"events": [event("page_view", sid, datetime.now(UTC))]})
    rr = [
        {"type": 4, "timestamp": ts, "data": {"href": "https://acme/"}},
        {"type": 3, "timestamp": ts + 500, "data": {"source": 2, "type": 2, "id": 12}},
    ]
    body = gzip.compress(json.dumps({"session_id": sid, "chunk_index": 0, "events": rr}).encode())
    r = await client.post(
        "/ingest/replay",
        content=body,
        headers={"content-encoding": "gzip", "content-type": "application/json"},
    )
    assert r.status_code == 200, r.text
    key = r.json()["stored"]
    assert key.endswith("/00000.json.gz") and "/2026-10-06/" in key
    assert json.loads(gzip.decompress(await client.store.get(key))) == rr
    row = await pg.fetchrow("SELECT event_count FROM replays WHERE session_id = %s", (sid,))
    assert row["event_count"] == 2
    assert (await pg.fetchrow("SELECT has_replay FROM sessions WHERE id = %s", (sid,)))["has_replay"]


async def test_postgres_blob_store_round_trip(pg, monkeypatch):
    from engine.storage import PgBlobStore, get_blob_store

    set_blob_store(None)
    assert isinstance(get_blob_store(), PgBlobStore)  # DATABASE_URL set, no bucket
    store = get_blob_store()
    key = f"replays/t/{uuid.uuid4().hex}/00000.json.gz"
    assert not await store.exists(key)
    await store.put(key, b"first")
    await store.put(key, b"second", "application/gzip")
    assert await store.exists(key)
    assert await store.get(key) == b"second"
    with pytest.raises(FileNotFoundError):
        await store.get(key + "x")
    monkeypatch.setenv("WHYDUNIT_BLOB_STORE", "local")
    set_blob_store(None)
    assert isinstance(get_blob_store(), LocalBlobStore)
    set_blob_store(None)
