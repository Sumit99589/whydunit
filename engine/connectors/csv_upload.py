"""Tier 3: CSV exports uploaded by the user. Nemotron Nano maps the file's columns to the evidence kind's schema;
the user confirms a preview; the confirmed file becomes a source for that kind."""

from __future__ import annotations

import difflib
import io
import json
import re
from datetime import UTC, datetime
from typing import Any

import polars as pl

from engine import db
from engine.connectors.base import KIND_SCHEMAS, BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window
from engine.runtime.llm import LLM, get_llm
from engine.runtime.schemas import new_id
from engine.storage import get_blob_store

MAX_BYTES = 20 * 1024 * 1024
TIME_COL = {
    "deploys": "created_at",
    "funnel_events": "ts",
    "sessions": "started_at",
    "ad_performance": "hour",
    "ad_changes": "ts",
    "payments": "created",
    "support_tickets": "created_at",
    "reviews": "created_at",
    "world_news": "published_at",
    "holidays": "date",
    "dependency_status": "started_at",
}
SYNONYMS = {
    "id": ["id", "charge id", "payment id", "payment intent", "ticket id", "uid"],
    "created": ["created", "created date (utc)", "created (utc)", "date", "created at", "timestamp", "time"],
    "created_at": ["created at", "created", "date", "timestamp", "opened"],
    "amount": ["amount", "amount (usd)", "total", "gross"],
    "currency": ["currency", "curr"],
    "status": ["status", "result", "state", "outcome"],
    "outcome_type": ["outcome type", "outcome", "network status"],
    "decline_code": ["decline reason", "decline code", "failure code", "failure reason", "error code"],
    "card_brand": ["card brand", "brand", "network"],
    "card_country": ["card issue country", "card country", "issuer country", "issuing country"],
    "country": ["country (metadata)", "customer country", "billing country", "country"],
    "subject": ["subject", "title"],
    "body": ["body", "message", "description", "text"],
    "channel": ["channel", "via"],
    "rating": ["rating", "stars", "score"],
    "platform": ["platform", "store", "source"],
    "title": ["title", "headline"],
    "hour": ["hour", "date", "day"],
    "campaign_id": ["campaign id"],
    "campaign_name": ["campaign", "campaign name"],
    "impressions": ["impressions", "impr", "impr."],
    "clicks": ["clicks"],
    "cost": ["cost", "spend", "amount spent"],
    "budget_limited": ["limited by budget", "budget limited", "status"],
}


def heuristic_mapping(kind: str, columns: list[str]) -> dict[str, str | None]:
    lower = {c.lower().strip(): c for c in columns}
    out: dict[str, str | None] = {}
    used: set[str] = set()
    for target in KIND_SCHEMAS[kind]:
        cands = SYNONYMS.get(target, [target.replace("_", " ")])
        hit = next((lower[c] for c in cands if c in lower and lower[c] not in used), None)
        if hit is None:
            close = difflib.get_close_matches(
                target.replace("_", " "), [c for c in lower if lower[c] not in used], 1, 0.75
            )
            hit = lower[close[0]] if close else None
        out[target] = hit
        if hit:
            used.add(hit)
    return out


async def llm_mapping(
    llm: LLM, kind: str, columns: list[str], sample: list[dict[str, Any]]
) -> dict[str, str | None]:
    prompt = (
        f"Map the columns of an uploaded CSV to the '{kind}' schema {KIND_SCHEMAS[kind]}.\nCSV columns: {columns}\n"
        f"Sample rows: {json.dumps(sample[:3], default=str)[:1500]}\n"
        'Return JSON {"mapping": {schema_column: csv_column or null}}. Use only the listed CSV columns.'
    )
    r = await llm.chat(
        "nano",
        [{"role": "user", "content": prompt}],
        json_mode=True,
        reasoning=False,
        temperature=0,
        tag="csv:mapping",
    )
    m = r.json().get("mapping", {})
    return {t: (m.get(t) if m.get(t) in columns else None) for t in KIND_SCHEMAS[kind]}


def _to_dt(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    s = str(v).strip().replace("Z", "+00:00")
    for fmt in (
        None,
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y",
    ):
        try:
            d = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def apply_mapping(kind: str, df: pl.DataFrame, mapping: dict[str, str | None]) -> pl.DataFrame:
    rows = []
    for r in df.to_dicts():
        out = {t: (r.get(src) if src else None) for t, src in mapping.items()}
        tcol = TIME_COL.get(kind)
        if tcol and tcol in out and kind != "holidays":
            out[tcol] = _to_dt(out[tcol])
        if kind == "payments":
            amt = out.get("amount")
            try:
                f = float(str(amt).replace(",", "")) if amt not in (None, "") else None
            except ValueError:
                f = None
            out["amount"] = (
                int(round(f * 100)) if f is not None and ("." in str(amt)) else (int(f) if f else None)
            )
            st = str(out.get("status") or "").lower()
            ok = bool(re.search(r"succe|paid|captured|authori", st))
            out["status"] = "succeeded" if ok else "requires_payment_method"
            if not out.get("outcome_type"):
                out["outcome_type"] = (
                    "authorized" if ok else ("issuer_declined" if out.get("decline_code") else "api_error")
                )
            out["currency"] = (out.get("currency") or "usd").lower()
            for k in ("card_country", "country"):
                if out.get(k):
                    out[k] = str(out[k]).upper()[:2]
        rows.append(out)
    return (
        pl.DataFrame(rows, infer_schema_length=None)
        if rows
        else pl.DataFrame({c: [] for c in KIND_SCHEMAS[kind]})
    )


async def ingest_upload(
    kind: str, filename: str, data: bytes, case_id: str | None = None, llm: LLM | None = None
) -> dict[str, Any]:
    if kind not in KIND_SCHEMAS:
        raise ValueError(f"unknown evidence kind {kind!r}")
    if len(data) > MAX_BYTES:
        raise ValueError("file too large (20 MB max)")
    try:
        df = pl.read_csv(
            io.BytesIO(data), infer_schema_length=1000, try_parse_dates=False, truncate_ragged_lines=True
        )
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"could not read the CSV: {e}") from e
    if df.height == 0 or df.width == 0:
        raise ValueError("the CSV is empty")
    uid = new_id("up")
    key = f"uploads/{uid}.csv"
    await get_blob_store().put(key, data, "text/csv")
    llm = llm or get_llm()
    columns = df.columns
    mapped_by = "rules"
    mapping = heuristic_mapping(kind, columns)
    if llm.available():
        try:
            mapping = await llm_mapping(llm, kind, columns, df.head(3).to_dicts())
            mapped_by = "Nemotron Nano"
        except Exception:  # noqa: BLE001
            mapped_by = "rules (model output unusable)"
    preview = apply_mapping(kind, df.head(8), mapping)
    up = {
        "id": uid,
        "kind": kind,
        "filename": filename[:200],
        "blob_key": key,
        "status": "pending",
        "columns": columns,
        "mapping": mapping,
        "mapped_by": mapped_by,
        "row_count": df.height,
        "case_id": case_id,
        "preview": json.loads(preview.write_json()),
    }
    await db.execute(
        """INSERT INTO uploads (id, kind, filename, blob_key, status, columns, mapping, mapped_by, preview, row_count, case_id)
           VALUES (%s,%s,%s,%s,'pending',%s,%s,%s,%s,%s,%s)""",
        (
            uid,
            kind,
            up["filename"],
            key,
            db.jsonb(columns),
            db.jsonb(mapping),
            mapped_by,
            db.jsonb(up["preview"]),
            df.height,
            case_id,
        ),
    )
    return up


async def confirm_upload(upload_id: str, mapping: dict[str, str | None] | None = None) -> dict[str, Any]:
    row = await db.fetchrow("SELECT * FROM uploads WHERE id = %s", (upload_id,))
    if not row:
        raise KeyError(upload_id)
    m = mapping or row["mapping"]
    bad = [v for v in m.values() if v and v not in row["columns"]]
    if bad:
        raise ValueError(f"mapping uses columns the file does not have: {bad}")
    await db.execute(
        "UPDATE uploads SET status = 'confirmed', mapping = %s, confirmed_at = now() WHERE id = %s",
        (db.jsonb(m), upload_id),
    )
    if row["case_id"]:
        await db.execute(
            "UPDATE evidence_requests SET status = 'fulfilled', upload_id = %s WHERE case_id = %s AND kind = %s",
            (upload_id, row["case_id"], row["kind"]),
        )
    return {**row, "status": "confirmed", "mapping": m}


class CSVUpload(BaseConnector):
    name = "csv_upload"
    tier = 3
    unavailable_reason = "no CSV uploaded for this kind yet"
    kinds = tuple(KIND_SCHEMAS)

    async def available(self) -> bool:
        return True

    async def available_for(self, kind: str) -> bool:
        try:
            row = await db.fetchrow(
                "SELECT 1 FROM uploads WHERE kind = %s AND status = 'confirmed' LIMIT 1", (kind,)
            )
            return bool(row)
        except Exception:  # noqa: BLE001
            return False

    async def fetch(
        self, kind: str, window: Window | None, filters: dict[str, Any] | None = None
    ) -> EvidenceBundle:
        ups = await db.fetch(
            "SELECT * FROM uploads WHERE kind = %s AND status = 'confirmed' ORDER BY confirmed_at DESC",
            (kind,),
        )
        store = get_blob_store()
        frames, names = [], []
        for u in ups:
            raw = await store.get(u["blob_key"])
            df = pl.read_csv(io.BytesIO(raw), infer_schema_length=1000, truncate_ragged_lines=True)
            frames.append(apply_mapping(kind, df, u["mapping"]))
            names.append(u["filename"])
        df = (
            pl.concat(frames, how="diagonal_relaxed")
            if frames
            else pl.DataFrame({c: [] for c in KIND_SCHEMAS[kind]})
        )
        tcol = TIME_COL.get(kind)
        if window and tcol in df.columns and df.height and kind != "holidays":
            df = df.filter(
                pl.col(tcol).is_not_null() & (pl.col(tcol) >= window.start) & (pl.col(tcol) < window.end)
            )
        return make_bundle(
            kind,
            self,
            df,
            window,
            query={"files": names},
            summary=f"{df.height:,} {kind.replace('_', ' ')} rows from uploaded CSV ({', '.join(names)}), "
            f"{fmt_window(window)}",
            data_ref={"source": "csv_upload", "uploads": [u["id"] for u in ups]},
        )
