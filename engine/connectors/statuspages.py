"""Tier 1: dependency incidents from Atlassian Statuspage JSON (…/api/v2/incidents.json)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from engine.connectors.base import Artifact, BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame
from engine.settings import load_config


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


class StatusPages(BaseConnector):
    name = "statuspages"
    tier = 1
    kinds = ("dependency_status",)

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def available(self) -> bool:
        return True

    async def _fetch_dependency_status(
        self, window: Window | None, filters: dict[str, Any]
    ) -> EvidenceBundle:
        deps = [d for d in load_config("company_profile")["dependencies"] if d.get("statuspage")]
        rows, checked, notes = [], [], []
        async with httpx.AsyncClient(transport=self.transport, timeout=20, follow_redirects=True) as c:
            results = await asyncio.gather(
                *(c.get(f"{d['statuspage'].rstrip('/')}/api/v2/incidents.json") for d in deps),
                return_exceptions=True,
            )
        for d, r in zip(deps, results, strict=True):
            if isinstance(r, Exception) or r.status_code != 200:
                notes.append(f"could not read {d['name']} status page")
                continue
            checked.append(d["name"])
            for inc in r.json().get("incidents", []):
                start, end = _ts(inc.get("started_at") or inc.get("created_at")), _ts(inc.get("resolved_at"))
                if window and (start is None or start >= window.end or (end and end < window.start)):
                    continue
                rows.append(
                    {
                        "service": d["name"],
                        "name": inc.get("name"),
                        "impact": inc.get("impact"),
                        "started_at": start,
                        "resolved_at": end,
                        "url": inc.get("shortlink"),
                        "components": ", ".join(x.get("name", "") for x in inc.get("components", [])),
                    }
                )
        unchecked = [
            d["name"] for d in load_config("company_profile")["dependencies"] if not d.get("statuspage")
        ]
        if unchecked:
            notes.append(f"no Statuspage feed for: {', '.join(unchecked)}")
        df = frame(rows, "dependency_status")
        major = [r for r in rows if r["impact"] in ("major", "critical")]
        summary = (
            f"Status pages checked: {', '.join(checked) or 'none'}; {df.height} incident(s) {fmt_window(window)}"
            + (f", {len(major)} major" if major else "")
        )
        return make_bundle(
            "dependency_status",
            self,
            df,
            window,
            query={"checked": checked},
            summary=summary,
            notes=notes,
            artifacts=[
                Artifact(type="link", ref=r["url"], caption=f"{r['service']}: {r['name']}")
                for r in rows[:5]
                if r["url"]
            ],
            data_ref={"source": "statuspage:/api/v2/incidents.json"},
        )
