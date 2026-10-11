"""Tier 3 uploads (CSV exports with column mapping) and the Connect page's connection tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

from engine import db
from engine.connectors import NoSource, live_registry
from engine.connectors.base import KINDS, Window
from engine.connectors.csv_upload import MAX_BYTES, confirm_upload, ingest_upload
from engine.settings import env

router = APIRouter(tags=["connect"])


def _admin(key: str | None) -> None:
    expected = env("WHYDUNIT_ADMIN_KEY")
    if expected and key != expected:
        raise HTTPException(403, "Making an upload a live evidence source needs the admin key.")


@router.post("/uploads")
async def upload(
    kind: str = Form(...), file: UploadFile = File(...), case_id: str | None = Form(None)
) -> dict[str, Any]:
    if kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(KINDS)}")
    data = await file.read(MAX_BYTES + 1)
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
async def test_connection(body: Test) -> dict[str, Any]:
    if body.kind not in KINDS:
        raise HTTPException(422, "unknown kind")
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
