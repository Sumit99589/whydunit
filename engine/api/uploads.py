"""Tier 3 uploads (CSV exports with column mapping) and the Connect page's connection tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel

from engine import db
from engine.connectors import NoSource, live_registry
from engine.connectors.base import KINDS, Window
from engine.connectors.csv_upload import MAX_BYTES, confirm_upload, ingest_upload
from engine.settings import env

router = APIRouter(tags=["connect"])


_hits: dict[tuple[str, str], list[float]] = {}
PUBLIC_UPLOAD_BYTES = 5 * 1024 * 1024


def limit(request: Request, bucket: str, per_hour: int, admin_key: str | None = None) -> None:
    """Per-IP hourly limit for public endpoints that cost money or storage (admins exempt)."""
    import time as _t

    if env("WHYDUNIT_ADMIN_KEY") and admin_key == env("WHYDUNIT_ADMIN_KEY"):
        return
    fwd = request.headers.get("x-forwarded-for")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
    now = _t.time()
    hits = [t for t in _hits.get((bucket, ip), []) if now - t < 3600]
    if len(hits) >= per_hour:
        raise HTTPException(429, f"Too many requests; try again within the hour (limit {per_hour} per hour).")
    _hits[(bucket, ip)] = hits + [now]


def _admin(key: str | None) -> None:
    expected = env("WHYDUNIT_ADMIN_KEY")
    if expected and key != expected:
        raise HTTPException(403, "Making an upload a live evidence source needs the admin key.")


@router.post("/uploads")
async def upload(
    request: Request,
    kind: str = Form(...),
    file: UploadFile = File(...),
    case_id: str | None = Form(None),
    x_admin_key: str | None = Header(default=None),
) -> dict[str, Any]:
    if kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(KINDS)}")
    limit(request, "upload", 5, x_admin_key)
    is_admin = bool(env("WHYDUNIT_ADMIN_KEY")) and x_admin_key == env("WHYDUNIT_ADMIN_KEY")
    cap = MAX_BYTES if is_admin or not env("WHYDUNIT_ADMIN_KEY") else PUBLIC_UPLOAD_BYTES
    data = await file.read(cap + 1)
    if len(data) > cap:
        raise HTTPException(413, f"file too large ({cap // (1024 * 1024)} MB max)")
    try:
        return await ingest_upload(kind, file.filename or "upload.csv", data, case_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class Confirm(BaseModel):
    mapping: dict[str, str | None] | None = None


@router.post("/uploads/{upload_id}/confirm")
async def confirm(
    upload_id: str, body: Confirm, x_admin_key: str | None = Header(default=None)
) -> dict[str, Any]:
    _admin(x_admin_key)
    try:
        up = await confirm_upload(upload_id, body.mapping)
    except KeyError as e:
        raise HTTPException(404, "no such upload") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"id": up["id"], "kind": up["kind"], "status": up["status"]}


@router.get("/uploads")
async def list_uploads() -> list[dict[str, Any]]:
    return await db.fetch(
        "SELECT id, kind, filename, status, mapped_by, row_count, case_id, created_at FROM uploads "
        "ORDER BY created_at DESC LIMIT 100"
    )


@router.get("/cases/{case_id}/requests")
async def requests(case_id: str) -> list[dict[str, Any]]:
    return await db.fetch(
        "SELECT * FROM evidence_requests WHERE case_id = %s ORDER BY created_at", (case_id,)
    )


class Test(BaseModel):
    kind: str


@router.post("/connect/test")
async def test_connection(
    body: Test, request: Request, x_admin_key: str | None = Header(default=None)
) -> dict[str, Any]:
    if body.kind not in KINDS:
        raise HTTPException(422, "unknown kind")
    limit(request, "connect_test", 10, x_admin_key)
    now = datetime.now(UTC)
    filters = {"query": "Acme Notes"} if body.kind == "world_news" else {}
    try:
        b = await live_registry().fetch(body.kind, Window(now - timedelta(days=7), now), filters)
    except NoSource as e:
        return {"ok": False, "kind": body.kind, "message": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "kind": body.kind, "message": f"{type(e).__name__}: {str(e)[:200]}"}
    return {
        "ok": True,
        "kind": body.kind,
        "connector": b.connector,
        "tier": b.tier,
        "tier_label": b.tier_label,
        "summary": b.summary,
        "notes": b.notes,
    }
