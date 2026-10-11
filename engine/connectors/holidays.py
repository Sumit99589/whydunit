"""Tier 1: public holidays from the Nager.Date public API (no key)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from engine.connectors.base import BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame
from engine.settings import load_config

# Nager.Date does not cover India; these fixed national holidays are added from the bundled list.
BUNDLED = Path(__file__).resolve().parent.parent / "fixtures" / "data" / "holidays_2026.json"


class Holidays(BaseConnector):
    name = "nager_holidays"
    tier = 1
    kinds = ("holidays",)

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def available(self) -> bool:
        return True

    async def _fetch_holidays(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        if window is None:
            raise ValueError("holidays needs a window")
        countries = filters.get("countries") or load_config("company_profile")["company"]["top_countries"]
        years = sorted({window.start.year, window.end.year})
        rows, notes = [], []
        async with httpx.AsyncClient(
            base_url="https://date.nager.at", transport=self.transport, timeout=20
        ) as c:
            for country in countries:
                for y in years:
                    r = await c.get(f"/api/v3/PublicHolidays/{y}/{country}")
                    if r.status_code == 204 or not r.content:
                        notes.append(f"Nager.Date has no data for {country}")
                        rows += [h for h in _bundled(country) if h["date"].startswith(str(y))]
                        continue
                    r.raise_for_status()
                    rows += [
                        {
                            "date": h["date"],
                            "country": country,
                            "name": h["name"],
                            "national": h.get("global", True),
                        }
                        for h in r.json()
                    ]
        lo, hi = window.start.date(), window.end.date()
        rows = [h for h in rows if lo <= date.fromisoformat(h["date"]) <= hi]
        df = frame(rows, "holidays")
        listed = ", ".join(f"{h['name']} ({h['country']}, {h['date']})" for h in rows[:5])
        return make_bundle(
            "holidays",
            self,
            df,
            window,
            query={"countries": countries},
            notes=notes,
            summary=f"Public holidays in {', '.join(countries)}, {fmt_window(window)}: " + (listed or "none"),
            data_ref={"source": "https://date.nager.at"},
        )


def _bundled(country: str) -> list[dict[str, Any]]:
    data = json.loads(BUNDLED.read_text())["holidays"]
    return [
        {"date": h["date"], "country": h["country"], "name": h["name"], "national": True}
        for h in data
        if h["country"] == country
    ]
