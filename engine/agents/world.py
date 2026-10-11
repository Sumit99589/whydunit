"""The World detective: did something outside the company cause this? News, holidays, dependency outages.

Absence of evidence is reported as an explicit checked-list, never as silence.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from engine.agents.base import COUNTRY, Detective, Tool
from engine.connectors.base import Window
from engine.runtime.schemas import Answer, Finding
from engine.settings import load_config

EVENT_WORDS = (
    r"launch|free tier|free plan|price cut|outage|down\b|disruption|strike|ban|regulation|acquir|shut"
)
DEP_FACTOR = {"Stripe": "payment_success_rate", "Vercel": "signup_rate", "Neon": "signup_rate"}


class WorldDetective(Detective):
    def __init__(self, ctx):
        super().__init__(
            ctx,
            name="world",
            title="World detective",
            mission="You own the outside world: news about competitors and the industry, public holidays "
            "in key countries, and outages at the services the product depends on.",
        )

    def queries(self) -> list[str]:
        prof = load_config("company_profile")
        c = prof["company"]
        qs = [f"{comp} launch OR free tier OR pricing" for comp in c.get("competitors", [])[:3]]
        qs.append(f"{c['industry']} team notes app launch")
        qs += [f"{d['name']} outage" for d in prof.get("dependencies", [])[:3]]
        return qs[:8]

    async def playbook(self) -> None:
        ctx = self.ctx
        w = ctx.case_window
        checked_news, hits = [], []
        for q in self.queries():
            b = await self.fetch("world_news", w, {"query": q})
            if b is None:
                break
            checked_news.append((q, b))
            for r in b.frame.to_dicts():
                hits.append({**r, "query": q, "evidence": b.id})
        relevant = await self.relevant(hits)
        hol = await self.fetch("holidays", Window(ctx.case.window_start, ctx.case.window_end))
        status = await self.fetch("dependency_status", Window(ctx.case.window_start, ctx.case.window_end))

        found = False
        for r in relevant[:2]:
            found = True
            pub = r["published_at"]
            self.add_finding(
                f"News in the window: “{r['title']}” ({r['source']}, {pub:%a %b %d}). A competitor move like this can "
                "pull would-be signups away.",
                [r["evidence"]],
                [],
                kind="inference",
                confidence=0.7,
            )
            self.propose(f"External event: {r['title']}", "signup_rate", {}, pub, [])
        if hol is not None and hol.row_count:
            for h in hol.frame.to_dicts():
                found = True
                day = datetime.fromisoformat(f"{h['date']}T00:00:00+00:00")
                self.add_finding(
                    f"{h['name']} was a public holiday in {COUNTRY.get(h['country'], h['country'])} on "
                    f"{day:%a %b %d}, inside the window; traffic from there would normally dip that day.",
                    [hol.id],
                    [],
                    kind="inference",
                    confidence=0.8,
                )
                self.propose(
                    f"{h['name']} in {COUNTRY.get(h['country'], h['country'])}",
                    "traffic",
                    {"country": h["country"]},
                    day,
                    [],
                    end=day + timedelta(days=1),
                )
        if status is not None and status.row_count:
            for s in status.frame.filter(pl.col("impact").is_in(["major", "critical"])).to_dicts():
                found = True
                factor = DEP_FACTOR.get(s["service"])
                self.add_finding(
                    f"{s['service']} reported a {s['impact']} incident “{s['name']}” from "
                    f"{s['started_at']:%a %b %d %H:%M} UTC"
                    + (f" to {s['resolved_at']:%H:%M} UTC" if s.get("resolved_at") else " (still open)")
                    + ".",
                    [status.id],
                    [],
                    confidence=0.85,
                )
                if factor:
                    self.propose(
                        f"{s['service']} outage: {s['name']}",
                        factor,
                        {},
                        s["started_at"],
                        [],
                        end=s.get("resolved_at"),
                    )
        # The checked-list, always.
        m_q = ctx.metric("news searches run", len(checked_news), "count", [b.id for _, b in checked_news])
        m_r = ctx.metric("news results reviewed", len(hits), "count", [b.id for _, b in checked_news])
        countries = load_config("company_profile")["company"]["top_countries"]
        parts = []
        if checked_news:
            parts.append(
                f"{len(checked_news)} time-bounded news searches with {len(hits)} results reviewed "
                f"(competitors, the industry, and outages at {', '.join(d['name'] for d in load_config('company_profile')['dependencies'][:3])})"
            )
        if hol is not None:
            parts.append(f"public holidays in {', '.join(COUNTRY.get(c, c) for c in countries)}")
        if status is not None:
            parts.append(
                "status pages ("
                + (status.query.get("checked") and ", ".join(status.query["checked"]) or "dependencies")
                + ")"
            )
        unchecked = [c.kind for c in self.cannot]
        ev_ids = [b.id for _, b in checked_news] + [x.id for x in (hol, status) if x is not None]
        if not found and ev_ids:
            self.add_finding(
                "No external cause found. Checked: "
                + "; ".join(parts)
                + "."
                + (f" Could not check: {', '.join(unchecked)}." if unchecked else ""),
                ev_ids,
                [m_q.id, m_r.id],
                confidence=0.8,
            )
        elif ev_ids:
            self.notes.append("checked: " + "; ".join(parts))

    async def relevant(self, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep results that describe an event in the window (Nano judges when available; rules otherwise)."""
        ctx = self.ctx
        lo = ctx.case.window_start - timedelta(days=2)
        cands = [h for h in hits if h.get("published_at") and lo <= h["published_at"] <= ctx.case.window_end]
        seen, uniq = set(), []
        for h in cands:
            if h["url"] not in seen:
                seen.add(h["url"])
                uniq.append(h)
        if not uniq:
            return []
        if ctx.llm.available():
            try:
                prompt = (
                    "Acme Notes (a team note-taking SaaS) saw signups and paid subscriptions drop. For each news "
                    "item, answer whether it describes a concrete external event that could plausibly affect "
                    'Acme\'s signups or payments in this period. Return JSON {"relevant": [true/false, ...]}.\n\n'
                    + "\n".join(f"{i + 1}. {h['title']} — {h['content'][:200]}" for i, h in enumerate(uniq))
                )
                r = await ctx.llm.chat(
                    "nano",
                    [{"role": "user", "content": prompt}],
                    json_mode=True,
                    reasoning=False,
                    temperature=0,
                    meter=ctx.meter,
                    tag="world:relevance",
                )
                flags = r.json().get("relevant", [])
                if len(flags) == len(uniq):
                    return [h for h, f in zip(uniq, flags, strict=True) if f]
            except Exception:  # noqa: BLE001 - fall back to rules
                pass
        return [h for h in uniq if re.search(EVENT_WORDS, (h["title"] + " " + h["content"]).lower())]

    async def answer_external_release(self, q):
        """Was there a browser/OS release or known breakage that could explain an engine-specific drop?"""

        at = datetime.fromisoformat(q.params["at"]) if isinstance(q.params["at"], str) else q.params["at"]
        engine = q.params.get("engine", "webkit")
        names = {
            "webkit": ["Safari", "iOS", "WebKit"],
            "chromium": ["Chrome", "Chromium"],
            "firefox": ["Firefox"],
        }[engine]
        w = Window(at - timedelta(days=3), at + timedelta(hours=12))
        found, evs = [], []
        for n in names[:2]:
            b = await self.fetch("world_news", w, {"query": f"{n} update release bug"})
            if b is None:
                break
            evs.append(b.id)
            found += [
                r
                for r in b.frame.to_dicts()
                if re.search(rf"\b{n.lower()}\b", (r["title"] + r["content"]).lower())
                and re.search(r"update|release|bug|broke|regression", (r["title"] + r["content"]).lower())
            ]
        if not evs:
            return Answer(
                question_id=q.id,
                detective=self.name,
                verdict="cannot_determine",
                text="Cannot search the news (no news source).",
            )
        if found:
            f = await self.validated(
                Finding(
                    detective=self.name,
                    kind="observed",
                    evidence_ids=evs,
                    claim=(f"Possible alternative: “{found[0]['title']}” was published around then."),
                )
            )
            return Answer(
                question_id=q.id, detective=self.name, text=f.claim, findings=[f], verdict="contradicts"
            )
        f = await self.validated(
            Finding(
                detective=self.name,
                kind="observed",
                evidence_ids=evs,
                claim=(
                    f"No {' or '.join(names[:2])} release or known breakage was reported in the three days before "
                    f"{at:%a %b %d %H:%M} UTC, so a browser update does not explain it."
                ),
            )
        )
        return Answer(question_id=q.id, detective=self.name, text=f.claim, findings=[f], verdict="supports")

    async def answer_external_event(self, q):
        """Holiday or outage that could explain a drop in a segment around a time?"""

        country = (q.params.get("segment") or {}).get("country")
        at = datetime.fromisoformat(q.params["at"]) if isinstance(q.params["at"], str) else q.params["at"]
        hol = await self.fetch(
            "holidays",
            Window(at - timedelta(days=1), at + timedelta(days=1)),
            {"countries": [country]} if country else {},
        )
        if hol is None:
            return Answer(
                question_id=q.id, detective=self.name, verdict="cannot_determine", text="No holiday source."
            )
        rows = [h for h in hol.frame.to_dicts() if not country or h["country"] == country]
        if rows:
            h = rows[0]
            f = await self.validated(
                Finding(
                    detective=self.name,
                    kind="observed",
                    evidence_ids=[hol.id],
                    claim=(
                        f"{h['name']} is a public holiday in {COUNTRY.get(h['country'], h['country'])} on that day."
                    ),
                )
            )
            return Answer(
                question_id=q.id, detective=self.name, text=f.claim, findings=[f], verdict="supports"
            )
        return Answer(
            question_id=q.id,
            detective=self.name,
            verdict="neutral",
            text=f"No public holiday in {COUNTRY.get(country, country or 'the top countries')} around then.",
        )

    def tools(self) -> list[Tool]:
        return []
