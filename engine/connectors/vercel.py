"""Tier 1: Vercel production deployments of Acme (each merge = an immutable deployment URL)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from engine.connectors.base import BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame
from engine.settings import env


class Vercel(BaseConnector):
    name = "vercel"
    tier = 1
    priority = 10
    kinds = ("deploys",)
    needs_env = ("VERCEL_TOKEN",)

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        params = {"teamId": env("VERCEL_TEAM_ID")} if env("VERCEL_TEAM_ID") else {}
        return httpx.AsyncClient(
            base_url="https://api.vercel.com",
            transport=self.transport,
            timeout=30,
            headers={"authorization": f"Bearer {env('VERCEL_TOKEN')}"},
            params=params,
        )

    async def _fetch_deploys(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        project = filters.get("project") or env("VERCEL_ACME_PROJECT", "acme-demo")
        q: dict[str, Any] = {"app": project, "target": "production", "limit": 100}
        if window:
            q["since"] = int(window.start.timestamp() * 1000)
            q["until"] = int(window.end.timestamp() * 1000)
        rows, nxt = [], None
        async with self._client() as c:
            for _ in range(10):
                if nxt:
                    q["until"] = nxt
                r = await c.get("/v6/deployments", params=q)
                r.raise_for_status()
                data = r.json()
                for d in data.get("deployments", []):
                    meta = d.get("meta") or {}
                    rows.append(
                        {
                            "id": d["uid"],
                            "url": f"https://{d['url']}",
                            "git_sha": meta.get("githubCommitSha"),
                            "created_at": datetime.fromtimestamp(d["created"] / 1000, tz=UTC),
                            "commit_message": meta.get("githubCommitMessage", ""),
                            "author": meta.get("githubCommitAuthorLogin")
                            or (d.get("creator") or {}).get("username"),
                            "state": d.get("readyState") or d.get("state"),
                            "git_ref": meta.get("githubCommitRef"),
                            "provider": "vercel",
                        }
                    )
                nxt = (data.get("pagination") or {}).get("next")
                if not nxt:
                    break
        df = frame(sorted(rows, key=lambda r: r["created_at"]), "deploys")
        return make_bundle(
            "deploys",
            self,
            df,
            window,
            query={"project": project},
            summary=f"{df.height} production deployments of {project} on Vercel, {fmt_window(window)}",
            data_ref={"source": "vercel:/v6/deployments", "project": project},
        )
