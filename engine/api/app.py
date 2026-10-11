"""FastAPI application: ingest, cases, stream, fixes, playground, connect, evals."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from engine import db
from engine.api import ingest
from engine.settings import env


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await db.close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="Whydunit engine", version="0.1.0", lifespan=lifespan)
    origins = [o.strip() for o in (env("CORS_ORIGINS", "*") or "*").split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        max_age=3600,
    )
    app.include_router(ingest.router)

    @app.get("/health")
    async def health() -> dict:
        row = await db.fetchrow("SELECT 1 AS ok")
        return {"ok": bool(row and row["ok"] == 1)}

    return app


app = create_app()
