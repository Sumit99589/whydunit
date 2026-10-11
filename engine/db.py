"""Postgres access. Neon in production (DATABASE_URL); an embedded `pgserver` Postgres in local dev and tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from engine.settings import ROOT, env

_pool: AsyncConnectionPool | None = None
_dev_server = None


def _embedded_url(dbname: str = "postgres") -> str:
    global _dev_server
    if _dev_server is None:
        import pgserver  # dev dependency

        _dev_server = pgserver.get_server(ROOT / ".pgdata", cleanup_mode=None)
    uri = _dev_server.get_uri()  # postgresql://postgres:@/postgres?host=/abs/.pgdata
    host = parse_qs(urlparse(uri).query)["host"][0]
    return f"postgresql://postgres@/{dbname}?host={quote(host, safe='/')}"


def database_url() -> str:
    """libpq-style URL (postgresql://…) for psycopg."""
    url = env("DATABASE_URL")
    if url:
        return url.replace("postgresql+psycopg://", "postgresql://").replace(
            "postgres://", "postgresql://", 1
        )
    return _embedded_url(env("WHYDUNIT_DEV_DB", "postgres"))


def sqlalchemy_url(url: str | None = None) -> str:
    return (url or database_url()).replace("postgresql://", "postgresql+psycopg://", 1)


async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            database_url(),
            min_size=1,
            max_size=int(env("DB_POOL_MAX", "8")),
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        await _pool.open()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def set_pool(pool: AsyncConnectionPool | None) -> None:
    global _pool
    _pool = pool


@asynccontextmanager
async def connection() -> AsyncIterator[Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        yield conn


async def fetch(sql: str, params: Any = None) -> list[dict[str, Any]]:
    async with connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchall()


async def fetchrow(sql: str, params: Any = None) -> dict[str, Any] | None:
    rows = await fetch(sql, params)
    return rows[0] if rows else None


async def execute(sql: str, params: Any = None) -> int:
    async with connection() as conn:
        cur = await conn.execute(sql, params)
        return cur.rowcount


def jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda v: json.dumps(v, default=str))
