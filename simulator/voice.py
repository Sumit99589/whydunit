"""Support tickets and app reviews for the simulated customer base.

Background volume is steady; incident-related messages are *emergent*: a share of the visitors whose
signup was actually blocked, or whose card was actually declined, write in. Text comes from Nemotron
Nano when a key is configured, otherwise from templates.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from engine.runtime.llm import LLM, LLMUnavailable, get_llm

log = logging.getLogger("whydunit.sim.voice")

FIRST = [
    "Maya",
    "Lucas",
    "Priya",
    "Tom",
    "Ana",
    "Kenji",
    "Sofia",
    "Daniel",
    "Aisha",
    "Mateus",
    "Emma",
    "Ravi",
    "Chloe",
    "Jonas",
    "Fatima",
    "Leo",
    "Grace",
    "Omar",
    "Isabela",
    "Noah",
]
LAST = ["Silva", "Patel", "Nguyen", "Schmidt", "Costa", "Brown", "Kumar", "Martin", "Oliveira", "Weber"]

BACKGROUND_TOPICS = [
    ("billing_question", 0.22),
    ("feature_request", 0.25),
    ("login_help", 0.15),
    ("export_question", 0.12),
    ("sync_bug", 0.12),
    ("praise", 0.14),
]

SITUATIONS = {
    "billing_question": "asks how per-member billing works when adding teammates mid-month",
    "feature_request": "asks for a feature (pick one: dark mode, Markdown export, calendar view, offline mode)",
    "login_help": "cannot find the magic-link email to log in",
    "export_question": "wants to export all notes to PDF before a board meeting",
    "sync_bug": "says a note edited on two laptops showed an old version for a minute",
    "praise": "says decision records saved their team a meeting this week",
    "signup_broken": "tried to create an account but tapping the Create account button does nothing, even after "
    "tapping several times",
    "card_declined": "their card was declined when upgrading to Pro although it works elsewhere",
}

TEMPLATES = {
    "billing_question": [
        (
            "Billing for new members",
            "If I add two people halfway through the month, am I charged "
            "for the full month for them? Want to get this right before inviting the team.",
        )
    ],
    "feature_request": [
        ("Dark mode?", "Love Acme so far. Any plans for a dark mode? Late-night writing is rough."),
        ("Markdown export", "Could you add Markdown export? We keep a copy of decisions in git."),
    ],
    "login_help": [
        (
            "Login link not arriving",
            "I requested the login link three times and nothing came. Checked spam too. Can you help?",
        )
    ],
    "export_question": [
        (
            "Export to PDF",
            "Is there a way to export a whole workspace to PDF? Need it for a board pack tomorrow.",
        )
    ],
    "sync_bug": [
        (
            "Old version showed up",
            "Edited a note on my laptop, opened it on my other machine and saw the "
            "old text for a minute before it updated. Is that expected?",
        )
    ],
    "praise": [
        (
            "Decision records are great",
            "Just wanted to say decision records saved us a whole meeting this week. Nice work.",
        )
    ],
    "signup_broken": [
        (
            "Can't sign up",
            "I'm trying to create an account on my {device} but the Create account "
            "button doesn't do anything. I tapped it like five times. Is the site down?",
        ),
        (
            "Sign up button not working",
            "Nothing happens when I press Create account. Filled in everything. Using {browser} on {os}.",
        ),
    ],
    "card_declined": [
        (
            "Card declined",
            "My card got declined when I tried to upgrade to Pro, but it works "
            "everywhere else. I'm in {country_name}.",
        ),
        (
            "Payment failed",
            "Tried twice to pay for Pro and both times it said declined. Bank says "
            "nothing is wrong on their side.",
        ),
    ],
}

REVIEW_TEMPLATES = {
    "positive": [
        (5, "Finally notes people read", "Decision records are a game changer for our team."),
        (4, "Clean and fast", "Simple, quick, does what it says. Wish it had dark mode."),
    ],
    "neutral": [(3, "Good but pricey", "Nice product but $12 per member adds up for a small team.")],
    "signup_broken": [
        (1, "Can't even sign up", "The sign up button does nothing on my iPhone. Gave up."),
        (2, "Broken on Safari", "Tried to register from Safari, button is dead. Shame."),
    ],
}

COUNTRY_NAMES = {
    "US": "the US",
    "GB": "the UK",
    "IN": "India",
    "DE": "Germany",
    "BR": "Brazil",
    "CA": "Canada",
    "FR": "France",
}


@dataclass
class Message:
    kind: str  # ticket | review
    topic: str
    created_at: datetime
    name: str
    email: str
    context: dict[str, Any] = field(default_factory=dict)
    subject: str = ""
    body: str = ""
    rating: int | None = None
    platform: str | None = None


def _person(rng: random.Random) -> tuple[str, str]:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    return f"{first} {last}", f"{first.lower()}.{last.lower()}{rng.randint(1, 999)}@example.com"


def plan_messages(
    window: tuple[datetime, datetime], journeys: list, cfg: dict[str, Any], rng: random.Random
) -> list[Message]:
    start, end = window
    hours = (end - start).total_seconds() / 3600
    out: list[Message] = []

    def at() -> datetime:
        return start + timedelta(seconds=rng.uniform(0, (end - start).total_seconds()))

    n_tickets = _poisson(rng, cfg.get("background_tickets_per_day", 6) * hours / 24)
    for _ in range(n_tickets):
        topic = _weighted(rng, BACKGROUND_TOPICS)
        name, email = _person(rng)
        out.append(Message("ticket", topic, at(), name, email))
    n_reviews = _poisson(rng, cfg.get("background_reviews_per_day", 2) * hours / 24)
    for _ in range(n_reviews):
        name, _ = _person(rng)
        out.append(Message("review", rng.choice(["positive", "positive", "neutral"]), at(), name, ""))

    for j in journeys:
        ctx = {
            "device": {"mobile": "phone", "tablet": "iPad", "desktop": "laptop"}[j.device],
            "browser": j.browser,
            "os": j.os,
            "country": j.country,
            "country_name": COUNTRY_NAMES.get(j.country, j.country),
        }
        if j.signup_blocked:
            if rng.random() < cfg.get("ticket_prob_blocked_signup", 0.05):
                name, email = _person(rng)
                out.append(
                    Message(
                        "ticket",
                        "signup_broken",
                        j.events[-1].ts + timedelta(minutes=rng.uniform(2, 30)),
                        name,
                        email,
                        ctx,
                    )
                )
            if rng.random() < cfg.get("review_prob_blocked_signup", 0.01):
                name, _ = _person(rng)
                out.append(
                    Message(
                        "review",
                        "signup_broken",
                        j.events[-1].ts + timedelta(hours=rng.uniform(1, 6)),
                        name,
                        "",
                        ctx,
                    )
                )
        if j.payment_outcome == "declined" and rng.random() < cfg.get("ticket_prob_declined", 0.10):
            name, email = _person(rng)
            out.append(
                Message(
                    "ticket",
                    "card_declined",
                    j.events[-1].ts + timedelta(minutes=rng.uniform(1, 20)),
                    name,
                    email,
                    ctx,
                )
            )
    # Messages caused by this window's journeys may land slightly after it; that's fine (real time-stamps).
    return sorted(out, key=lambda m: m.created_at)


async def write_text(msgs: list[Message], rng: random.Random, llm: LLM | None = None) -> None:
    llm = llm or get_llm()
    use_llm = llm.available()
    for m in msgs:
        if use_llm:
            try:
                await _llm_text(llm, m, rng)
                continue
            except (LLMUnavailable, ValueError, KeyError) as e:
                log.warning("Nano text generation failed (%s); using template", e)
                use_llm = False
            except Exception as e:  # noqa: BLE001
                log.warning("Nano text generation error %s; using template", type(e).__name__)
        _template_text(m, rng)


def _template_text(m: Message, rng: random.Random) -> None:
    if m.kind == "ticket":
        subject, body = rng.choice(TEMPLATES[m.topic])
        m.subject, m.body = (
            subject,
            body.format(
                **{
                    "device": "phone",
                    "browser": "my browser",
                    "os": "my phone",
                    "country_name": "my country",
                    **m.context,
                }
            ),
        )
    else:
        rating, title, body = rng.choice(REVIEW_TEMPLATES[m.topic])
        m.rating, m.subject, m.body = rating, title, body
        m.platform = (
            rng.choice(["app_store", "g2", "capterra"]) if m.topic != "signup_broken" else "app_store"
        )


async def _llm_text(llm: LLM, m: Message, rng: random.Random) -> None:
    situation = SITUATIONS.get(m.topic, "has a short opinion of the product")
    tone = rng.choice(["polite", "frustrated", "brief", "chatty", "matter-of-fact"])
    details = ", ".join(
        f"{k}: {v}" for k, v in m.context.items() if k in ("device", "browser", "os", "country_name")
    )
    if m.kind == "ticket":
        prompt = (
            f"Write a realistic support message to Acme Notes (a team note-taking SaaS). The customer "
            f"{situation}. Tone: {tone}. {('Context: ' + details + '.') if details else ''} "
            f"Customer name: {m.name}. 1-4 sentences, plain text, no signature. "
            'Return JSON: {"subject": "...", "body": "..."}'
        )
    else:
        sentiment = {
            "positive": "happy",
            "neutral": "mixed",
            "signup_broken": "angry because signup is broken",
        }[m.topic]
        prompt = (
            f"Write a short app-store style review of Acme Notes (team note-taking SaaS) by a {sentiment} "
            f"user. Tone: {tone}. {('Context: ' + details + '.') if details else ''} Reviewer: {m.name}. "
            'Return JSON: {"rating": 1-5, "title": "...", "body": "..."}'
        )
    r = await llm.chat(
        "nano",
        [{"role": "user", "content": prompt}],
        temperature=0.9,
        max_tokens=300,
        json_mode=True,
        tag=f"sim:voice:{m.topic}",
    )
    data = r.json()
    if m.kind == "ticket":
        m.subject, m.body = str(data["subject"])[:120], str(data["body"])[:1500]
    else:
        m.rating = max(1, min(5, int(data["rating"])))
        m.subject, m.body = str(data["title"])[:120], str(data["body"])[:1500]
        m.platform = (
            "app_store" if m.topic == "signup_broken" else rng.choice(["app_store", "g2", "capterra"])
        )


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth; lam is small here.
    import math

    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _weighted(rng: random.Random, items: list[tuple[str, float]]) -> str:
    x, acc = rng.random() * sum(w for _, w in items), 0.0
    for name, w in items:
        acc += w
        if x <= acc:
            return name
    return items[-1][0]
