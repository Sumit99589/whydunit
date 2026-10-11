"""FastAPI application: ingest, cases, stream, fixes, playground, connect, evals."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from engine import db
from engine.api import cases, ingest, uploads
from engine.mock_ads import api as mock_ads_api
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
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["*"],
        max_age=3600,
    )
    app.include_router(ingest.router)
    app.include_router(cases.router)
    app.include_router(uploads.router)
    app.include_router(mock_ads_api.router)

    @app.get("/connect")
    async def connect() -> dict:
        """Each evidence kind's connector ladder and which tier is active (live world)."""
        from engine.connectors import live_registry
        from engine.runtime.runner_client import RunnerClient

        reg = live_registry()
        return {"kinds": await reg.overview(), "runner": await RunnerClient().describe()}

    @app.get("/evals")
    async def evals() -> dict:
        """The published evaluation results (engine/evals/results.json)."""
        import json

        from engine.evals.run import RESULTS

        return json.loads(RESULTS.read_text()) if RESULTS.exists() else {"summary": None, "scenarios": []}

    @app.get("/health")
    async def health() -> dict:
        row = await db.fetchrow("SELECT 1 AS ok")
        return {"ok": bool(row and row["ok"] == 1)}

    return app


app = create_app()
