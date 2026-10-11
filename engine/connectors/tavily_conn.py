"""Tavily: time-bounded news search and page extraction (the World and Voice detectives' public-web eyes).

Tavily is tier 1 for `world_news` because it is the official API for that kind; the evidence it returns is
public web content, which the lead weighs like any outside source.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from engine.connectors.base import Artifact, BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame
from engine.settings import env


def _published(r: dict[str, Any]) -> datetime | None:
    raw = r.get("published_date") or r.get("published_at")
    if not raw:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            d = datetime.strptime(raw, fmt)
            return d if d.tzinfo else d.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


class Tavily(BaseConnector):
    name = "tavily"
    tier = 1
    kinds = ("world_news",)
    needs_env = ("TAVILY_API_KEY",)

    def __init__(self, client: Any = None):
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from tavily import AsyncTavilyClient

            self._client = AsyncTavilyClient(api_key=env("TAVILY_API_KEY"))
        return self._client

    async def _fetch_world_news(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        query = filters.get("query")
        if not query:
            raise ValueError("world_news needs a query")
        kw: dict[str, Any] = {
            "topic": filters.get("topic", "news"),
            "max_results": int(filters.get("max_results", 8)),
            "search_depth": "basic",
            "include_answer": False,
        }
        if window:
            # Tavily dates are inclusive days; pad a day each side and filter precisely below.
            kw["start_date"] = (window.start - timedelta(days=1)).date().isoformat()
            kw["end_date"] = (window.end + timedelta(days=1)).date().isoformat()
        res = await self.client.search(query, **kw)
        rows = []
        for r in res.get("results", []):
            pub = _published(r)
            if (
                window
                and pub
                and not (window.start - timedelta(days=1) <= pub <= window.end + timedelta(days=1))
            ):
                continue
            rows.append(
                {
                    "published_at": pub,
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "source": (r.get("url", "").split("/")[2] if "://" in r.get("url", "") else ""),
                    "content": (r.get("content") or "")[:1200],
                    "score": r.get("score"),
                    "query": query,
                }
            )
        df = frame(rows, "world_news")
        summary = f"Tavily news search “{query}”, {fmt_window(window)}: {df.height} result(s)" + (
            "" if df.height else " — nothing relevant found"
        )
        return make_bundle(
            "world_news",
            self,
            df,
            window,
            query={"query": query, **kw},
            summary=summary,
            artifacts=[Artifact(type="link", ref=r["url"], caption=r["title"]) for r in rows[:5]],
            data_ref={"source": "tavily:/search", "request_id": res.get("request_id")},
        )

    async def extract(self, urls: list[str]) -> list[dict[str, Any]]:
        res = await self.client.extract(urls, format="text")
        return [
            {"url": r.get("url"), "content": (r.get("raw_content") or "")[:4000]}
            for r in res.get("results", [])
        ]
