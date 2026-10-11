"""Tier 1: GitHub — commits on Acme's main branch (a deploys fallback), compare diffs and pull requests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from engine.connectors.base import Artifact, BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame
from engine.settings import env


class GitHub(BaseConnector):
    name = "github"
    tier = 1
    priority = 0  # Vercel is preferred for deploys; GitHub supplies diffs
    kinds = ("deploys",)
    needs_env = ("GITHUB_TOKEN",)

    def __init__(self, repo: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.repo = repo or env("ACME_REPO", "Sumit99589/acme-demo")
        self.transport = transport

    async def available(self) -> bool:
        return bool(env("ACME_GITHUB_TOKEN") or env("GITHUB_TOKEN"))

    def _client(self, accept: str = "application/vnd.github+json") -> httpx.AsyncClient:
        token = env("ACME_GITHUB_TOKEN") or env("GITHUB_TOKEN")
        return httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=self.transport,
            timeout=30,
            headers={
                "authorization": f"Bearer {token}",
                "accept": accept,
                "x-github-api-version": "2022-11-28",
            },
        )

    async def _fetch_deploys(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        params: dict[str, Any] = {"sha": filters.get("branch", "main"), "per_page": 100}
        if window:
            params |= {"since": window.start.isoformat(), "until": window.end.isoformat()}
        async with self._client() as c:
            r = await c.get(f"/repos/{self.repo}/commits", params=params)
            r.raise_for_status()
        rows = [
            {
                "id": cm["sha"][:12],
                "url": cm["html_url"],
                "git_sha": cm["sha"],
                "created_at": datetime.fromisoformat(
                    cm["commit"]["committer"]["date"].replace("Z", "+00:00")
                ),
                "commit_message": cm["commit"]["message"].split("\n")[0],
                "author": (cm.get("author") or {}).get("login") or cm["commit"]["author"]["name"],
                "state": "MERGED",
                "provider": "github",
            }
            for cm in r.json()
        ]
        df = frame(sorted(rows, key=lambda x: x["created_at"]), "deploys")
        return make_bundle(
            "deploys",
            self,
            df,
            window,
            query=params,
            summary=f"{df.height} commits on {self.repo}@{params['sha']}, {fmt_window(window)} "
            "(no deployment URLs: GitHub only)",
            data_ref={"source": f"github:{self.repo}/commits"},
        )

    async def compare(self, base: str, head: str) -> dict[str, Any]:
        """Diff between two commits, as text plus per-file stats."""
        async with self._client() as c:
            meta = await c.get(f"/repos/{self.repo}/compare/{base}...{head}")
            meta.raise_for_status()
        async with self._client("application/vnd.github.diff") as c:
            diff = await c.get(f"/repos/{self.repo}/compare/{base}...{head}")
            diff.raise_for_status()
        m = meta.json()
        return {
            "base": base,
            "head": head,
            "url": m.get("html_url"),
            "diff": diff.text,
            "commits": [
                {"sha": x["sha"], "message": x["commit"]["message"].split("\n")[0]}
                for x in m.get("commits", [])
            ],
            "files": [
                {"filename": f["filename"], "additions": f["additions"], "deletions": f["deletions"]}
                for f in m.get("files", [])
            ],
            "artifact": Artifact(type="diff", ref=m.get("html_url"), caption=f"{base[:7]}…{head[:7]}"),
        }

    async def pulls(self, state: str = "closed", per_page: int = 30) -> list[dict[str, Any]]:
        async with self._client() as c:
            r = await c.get(
                f"/repos/{self.repo}/pulls",
                params={"state": state, "per_page": per_page, "sort": "updated", "direction": "desc"},
            )
            r.raise_for_status()
        return [
            {
                "number": p["number"],
                "title": p["title"],
                "merged_at": p.get("merged_at"),
                "url": p["html_url"],
                "merge_commit_sha": p.get("merge_commit_sha"),
                "head": p["head"]["ref"],
            }
            for p in r.json()
        ]
