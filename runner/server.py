"""HTTP mode for a Nebius Serverless Endpoint: the same jobs, synchronously."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException

from engine.settings import env
from runner import jobs

app = FastAPI(title="Whydunit runner")


def _auth(key: str | None) -> None:
    expected = env("RUNNER_TOKEN")
    if expected and key != expected:
        raise HTTPException(403, "bad runner token")


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/run-flows")
async def run_flows(
    spec: dict[str, Any], x_runner_token: str | None = Header(default=None)
) -> dict[str, Any]:
    _auth(x_runner_token)
    return await jobs.run_flows(spec)


@app.post("/render-replay")
async def render_replay(
    spec: dict[str, Any], x_runner_token: str | None = Header(default=None)
) -> dict[str, Any]:
    _auth(x_runner_token)
    return await jobs.render_replays(spec)
