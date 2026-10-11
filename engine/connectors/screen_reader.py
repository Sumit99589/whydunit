"""Tier 4: screen reading. When a vendor has no usable API, the browser runner opens its dashboard read-only and
screenshots it; Nemotron Nano Omni turns the tables into rows. Every bundle carries the screenshot for audit and
is tagged "screen-read, medium confidence". Without a vision model, the rendered table text is used instead
(and labelled as such).

Demo target: the SIMULATED ad platform's dashboard with its API switched off ("no-API mode").
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import polars as pl

from engine.connectors.base import Artifact, BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window
from engine.runtime.llm import LLM, get_llm
from engine.runtime.runner_client import RunnerClient
from engine.settings import env
from engine.storage import get_blob_store

Capture = Callable[[list[dict[str, Any]]], Awaitable[dict[str, Any]]]


def _num(s: Any) -> float | None:
    if s is None:
        return None
    m = re.search(r"-?[\d,]+(?:\.\d+)?", str(s))
    return float(m.group(0).replace(",", "")) if m else None


def _day(s: str) -> datetime | None:
    s = str(s).strip()
    try:
        return datetime.fromisoformat(s[:10]).replace(tzinfo=UTC)
    except ValueError:
        return None


def _when(s: str) -> datetime | None:
    s = str(s).replace(" UTC", "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s[:16], fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def performance_from_rows(rows: list[list[str]]) -> list[dict[str, Any]]:
    """Daily performance table: Date | Campaign | Impr. | Clicks | Cost | Status."""
    out = []
    for r in rows[1:]:
        if len(r) < 6:
            continue
        day = _day(r[0])
        if not day:
            continue
        status = r[5]
        m = re.search(r"from (\d{1,2}):00", status)
        out.append(
            {
                "hour": day,
                "campaign_id": None,
                "campaign_name": r[1],
                "impressions": int(_num(r[2]) or 0),
                "clicks": int(_num(r[3]) or 0),
                "cost": _num(r[4]) or 0.0,
                "budget_limited": "limited" in status.lower(),
                "first_limited_hour": int(m.group(1)) if m else None,
                "granularity": "day",
            }
        )
    return out


def changes_from_rows(rows: list[list[str]]) -> list[dict[str, Any]]:
    """Change history table: When | Campaign | Change | Old → New | User."""
    out = []
    for r in rows[1:]:
        if len(r) < 5:
            continue
        when = _when(r[0])
        vals = re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", r[3])
        if not when or len(vals) < 2:
            continue
        out.append(
            {
                "ts": when,
                "campaign_id": None,
                "campaign_name": r[1],
                "field": "daily_budget",
                "old_value": float(vals[0].replace(",", "")),
                "new_value": float(vals[1].replace(",", "")),
                "user_email": r[4],
                "client_type": "screen-read",
            }
        )
    return out


class ScreenReader(BaseConnector):
    name = "screen_reader"
    tier = 4
    kinds = ("ad_performance", "ad_changes")
    unavailable_reason = "needs a dashboard URL and a browser runner"

    def __init__(
        self, dashboard_url: str | None = None, capture: Capture | None = None, llm: LLM | None = None
    ):
        self.url = (
            dashboard_url
            or env("MOCK_ADS_DASHBOARD_URL")
            or (
                f"{env('WHYDUNIT_ENGINE_URL').rstrip('/')}/mock-ads/?days=21"
                if env("WHYDUNIT_ENGINE_URL")
                else None
            )
        )
        self._capture = capture
        self._llm = llm
        self._cache: dict[str, Any] | None = None

    async def available(self) -> bool:
        if not self.url:
            return False
        if self._capture is not None:
            return True
        try:
            await RunnerClient().pick()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def _read(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache
        capture = self._capture or RunnerClient().capture
        res = await capture([{"url": self.url, "selectors": ["#daily", "#changes"]}])
        page = res["pages"][0]
        sections = {s["selector"]: s for s in page["sections"]}
        llm = self._llm or get_llm()
        perf, changes, method = None, None, "rendered table text (no vision model available)"
        if llm.available():
            try:
                perf, changes = await self._omni(llm, sections)
                method = "Nemotron Nano Omni reading the screenshot"
            except Exception:  # noqa: BLE001 - fall back to the page text
                perf = changes = None
        if perf is None:
            perf = performance_from_rows(sections.get("#daily", {}).get("rows", []))
            changes = changes_from_rows(sections.get("#changes", {}).get("rows", []))
        self._cache = {"perf": perf, "changes": changes, "method": method, "page": page, "sections": sections}
        return self._cache

    async def _omni(
        self, llm: LLM, sections: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        store = get_blob_store()
        daily_png = await store.get(sections["#daily"]["screenshot_key"])
        r = await llm.describe_images(
            "This is a 'Daily performance' table from an ad platform dashboard. Transcribe every row as JSON "
            '{"rows": [["date", "campaign", "impressions", "clicks", "cost", "status"], ...]} with the header row first, '
            "exactly as shown (keep 'Limited by budget from HH:00' text).",
            [daily_png],
            json_mode=True,
            tag="screen:daily",
        )
        perf = performance_from_rows(r.json()["rows"])
        changes: list[dict[str, Any]] = []
        if "#changes" in sections:
            ch_png = await store.get(sections["#changes"]["screenshot_key"])
            r2 = await llm.describe_images(
                "This is a 'Change history' table from an ad platform dashboard. Transcribe every row as JSON "
                '{"rows": [["when", "campaign", "change", "old → new", "user"], ...]} with the header row first, exactly '
                "as shown.",
                [ch_png],
                json_mode=True,
                tag="screen:changes",
            )
            changes = changes_from_rows(r2.json()["rows"])
        if not perf:
            raise ValueError("Omni returned no rows")
        return perf, changes

    async def fetch(
        self, kind: str, window: Window | None, filters: dict[str, Any] | None = None
    ) -> EvidenceBundle:
        got = await self._read()
        key = "#daily" if kind == "ad_performance" else "#changes"
        rows = got["perf"] if kind == "ad_performance" else got["changes"]
        df = pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()
        tcol = "hour" if kind == "ad_performance" else "ts"
        if window and df.height:
            df = df.filter(
                (pl.col(tcol) >= window.start.replace(hour=0, minute=0)) & (pl.col(tcol) < window.end)
            )
        if not df.height:
            from engine.connectors.base import empty_frame

            df = empty_frame(kind)
        shot = got["sections"].get(key, {}).get("screenshot_key") or got["page"]["screenshot_key"]
        return make_bundle(
            kind,
            self,
            df,
            window,
            query={"dashboard": self.url, "method": got["method"]},
            summary=(
                f"{df.height} {'daily rows' if kind == 'ad_performance' else 'changes'} read from the ad platform's "
                f"dashboard by screen reading ({got['method']}), {fmt_window(window)}; medium confidence"
            ),
            artifacts=[
                Artifact(type="screenshot", ref=shot, caption="Dashboard as read", meta={"url": self.url})
            ],
            notes=["screen-read, medium confidence"],
            data_ref={"source": "screen_reader", "dashboard": self.url, "method": got["method"]},
        )
