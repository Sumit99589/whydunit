"""The Voice detective: what are customers saying in support tickets, reviews and in public?"""

from __future__ import annotations

import math
import re

import polars as pl

from engine.agents.base import Detective, Tool
from engine.connectors.base import Artifact, Window
from engine.settings import load_config

TOPICS = {
    "signup_problem": r"sign ?up|create (an )?account|register|button (does|did)n'?t|nothing happens|can'?t (even )?sign",
    "payment_problem": r"card|declin|payment|charge|pay for|upgrade",
    "login_problem": r"log ?in|magic.?link|password reset|sign in",
    "billing_question": r"billing|invoice|charged for|per member|refund",
    "feature_request": r"dark mode|export|feature|would love|any plans|calendar|offline",
    "sync_or_bug": r"old version|sync|bug|crash|lost|slow",
    "praise": r"love|great|game changer|saved us|nice work|thank",
}
LABEL = {
    "signup_problem": "can't sign up",
    "payment_problem": "payment declined or failed",
    "login_problem": "can't log in",
    "billing_question": "billing questions",
    "feature_request": "feature requests",
    "sync_or_bug": "sync bugs",
    "praise": "praise",
    "other": "other",
}


def keyword_topic(text: str) -> str:
    t = text.lower()
    for topic, pat in TOPICS.items():
        if re.search(pat, t):
            return topic
    return "other"


class VoiceDetective(Detective):
    def __init__(self, ctx):
        super().__init__(
            ctx,
            name="voice",
            title="Voice detective",
            mission="You own the voice of the customer: support tickets, app reviews and public chatter, "
            "clustered by topic, with spikes compared to the baseline and real quotes as evidence.",
        )

    async def classify(self, texts: list[str]) -> tuple[list[str], str]:
        """Nemotron Nano assigns topics in batches; keyword rules are the fallback."""
        if not self.ctx.llm.available() or not texts:
            return [keyword_topic(t) for t in texts], "keyword rules"
        out: list[str] = []
        topics = list(TOPICS) + ["other"]
        try:
            for i in range(0, len(texts), 25):
                batch = texts[i : i + 25]
                prompt = (
                    "Classify each customer message of a team-notes SaaS into exactly one topic from "
                    f'{topics}. Return JSON {{"topics": [...]}} with one topic per message, same order.\n\n'
                    + "\n".join(f"{k + 1}. {t[:300]}" for k, t in enumerate(batch))
                )
                r = await self.ctx.llm.chat(
                    "nano",
                    [{"role": "user", "content": prompt}],
                    json_mode=True,
                    reasoning=False,
                    temperature=0,
                    meter=self.ctx.meter,
                    tag="voice:cluster",
                )
                got = [t if t in topics else "other" for t in r.json().get("topics", [])]
                if len(got) != len(batch):
                    raise ValueError("topic count mismatch")
                out += got
            return out, "Nemotron Nano"
        except Exception:  # noqa: BLE001
            return [keyword_topic(t) for t in texts], "keyword rules (model output unusable)"

    async def playbook(self) -> None:
        ctx = self.ctx
        w = Window(ctx.case.baseline_start, ctx.case.window_end)
        frames, sources = [], []
        for kind in ("support_tickets", "reviews"):
            b = await self.fetch(kind, w)
            if b is None or b.frame.height == 0:
                continue
            f = b.frame
            text = (
                (f["subject"] if "subject" in f.columns else f["title"]).fill_null("")
                + ". "
                + f["body"].fill_null("")
            )
            frames.append(
                pl.DataFrame(
                    {
                        "created_at": f["created_at"].dt.convert_time_zone("UTC"),
                        "text": text,
                        "source": [kind] * f.height,
                        "rating": f["rating"] if "rating" in f.columns else [None] * f.height,
                    }
                )
            )
            sources.append(b.id)
        if frames:
            await self.topics(pl.concat(frames, how="diagonal_relaxed"), sources)
        await self.public_chatter()

    async def topics(self, df: pl.DataFrame, sources: list[str]) -> None:
        ctx = self.ctx
        topics, method = await self.classify(df["text"].to_list())
        df = df.with_columns(pl.Series("topic", topics))
        b_days = (ctx.case.baseline_end - ctx.case.baseline_start).total_seconds() / 86400
        w_days = (ctx.case.window_end - ctx.case.window_start).total_seconds() / 86400
        base = df.filter(
            (pl.col("created_at") >= ctx.case.baseline_start) & (pl.col("created_at") < ctx.case.baseline_end)
        )
        win = df.filter(
            (pl.col("created_at") >= ctx.case.window_start) & (pl.col("created_at") < ctx.case.window_end)
        )
        rows = []
        for t in sorted(set(topics)):
            n0, n1 = base.filter(pl.col("topic") == t).height, win.filter(pl.col("topic") == t).height
            exp = n0 / b_days * w_days
            # Poisson upper-tail surprise (with a floor so a topic that was silent can still spike).
            lam = max(exp, 0.5)
            z = (n1 - lam) / math.sqrt(lam)
            rows.append({"topic": t, "baseline": n0, "window": n1, "expected": exp, "z": z})
        rows.sort(key=lambda r: -r["z"])
        an = await self.analysis(
            "voice_topics",
            rows,
            f"Tickets and reviews by topic ({method}), window vs baseline",
            sources,
            Window(ctx.case.baseline_start, ctx.case.window_end),
            method=method,
        )
        self.checked.append(f"support tickets and reviews clustered by {method}")
        spikes = [
            r for r in rows if r["window"] >= 3 and r["z"] >= 3 and r["topic"] not in ("praise", "other")
        ]
        if not spikes:
            m_n = ctx.metric("customer messages in the window", win.height, "count", [an.id])
            self.add_finding(
                f"No unusual spike in what customers are saying: {win.height} messages in the window, topics "
                "in their usual proportions.",
                sources + [an.id],
                [m_n.id],
                confidence=0.75,
            )
            return
        for s in spikes[:2]:
            quotes = win.filter(pl.col("topic") == s["topic"]).sort("created_at").head(3)["text"].to_list()
            m0 = ctx.metric(f"{LABEL[s['topic']]} messages, baseline", s["baseline"], "count", [an.id])
            m1 = ctx.metric(f"{LABEL[s['topic']]} messages, window", s["window"], "count", [an.id])
            qev = await self.analysis(
                f"quotes_{s['topic']}",
                [{"quote": q} for q in quotes],
                f"Representative messages about {LABEL[s['topic']]}",
                [an.id],
                None,
            )
            qev.artifacts.extend(Artifact(type="quote", ref=q[:300]) for q in quotes)
            first = quotes[0][:160] if quotes else ""
            self.add_finding(
                f"Messages about “{LABEL[s['topic']]}” jumped from {s['baseline']} in the baseline to {s['window']} in the "
                f"window. One customer: “{first}”",
                sources + [an.id, qev.id],
                [m0.id, m1.id],
                confidence=0.85,
            )

    async def public_chatter(self) -> None:
        ctx = self.ctx
        name = load_config("company_profile")["company"]["name"]
        q = {"query": f'"{name}" problems OR outage OR down OR complaints'}
        b = None
        if ctx.registry.mode == "fixture":
            # Even in a fixture world, ask the real web (Tavily) whether anyone is talking about the product.
            try:
                tav = ctx.registry.get("tavily")
                if await tav.available():
                    b = await tav.fetch("world_news", ctx.case_window, q)
                    await ctx.pin_derived(b, self.name)
                    self.checked.append(f"world_news via tavily (tier {b.tier})")
            except Exception:  # noqa: BLE001 - fall back to the world's own news
                b = None
        if b is None:
            b = await self.fetch("world_news", ctx.case_window, q)
        if b is None:
            return
        if b.row_count == 0:
            self.add_finding(
                f"No public chatter about {name} found on the web for the window (searched with Tavily): "
                "whatever is happening is not visible publicly.",
                [b.id],
                [],
                confidence=0.7,
            )
        else:
            self.add_finding(
                f"Public web results mention {name} in the window; see the linked articles.",
                [b.id],
                [],
                kind="inference",
                confidence=0.5,
            )

    def tools(self) -> list[Tool]:
        return []
