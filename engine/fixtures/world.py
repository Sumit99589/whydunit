"""Fixture worlds: deterministic, back-dated, plantable copies of the Acme world in a DuckDB file.

    uv run whydunit world create --incidents deploy_bug:webkit,ads_budget_cap --start 2026-09-14 --days 14
    uv run whydunit world create --preset 3inc

Every source a detective can read has a table here (events, sessions, replays, deployments and flow
results, payments, ads, tickets, reviews, news, holidays, status incidents). The `meta` table holds the
ground truth: incident times, affected factor and segment, and each incident's true share of the drop,
computed exactly as Shapley values over counterfactual worlds that reuse the same random numbers.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import polars as pl
import yaml

from engine.fixtures import rrweb
from engine.fixtures.incidents import FIXTURE_COMPETITOR, Incident, conditions_for, parse_incidents
from engine.mock_ads.model import DEFAULT_CAMPAIGNS, Campaign, HourStats, simulate
from engine.settings import ROOT, load_config
from engine.world.model import PROBES, Journey, WorldModel
from simulator import voice

GENERATOR_VERSION = 1
DATA = Path(__file__).parent / "data"
WORLDS_DIR = ROOT / ".cache" / "worlds"
ACME_BASE = "https://acme-notes.vercel.app"

REGULAR_COMMITS = [
    ("copy: tighten pricing page headline", ["app/pricing/page.tsx"]),
    ("fix(onboarding): keep step order stable", ["app/onboarding/page.tsx"]),
    ("chore(deps): bump postgres to 3.4.9", ["package.json", "pnpm-lock.yaml"]),
    ("feat(help): add subject field to contact form", ["app/help/HelpForm.tsx"]),
    ("style: soften card shadows on landing", ["app/page.tsx"]),
    ("perf: lazy-load decision record preview", ["app/page.tsx"]),
    ("fix(checkout): clearer insufficient-funds message", ["app/checkout/CheckoutForm.tsx"]),
    ("docs: README run instructions", ["README.md"]),
]


@dataclass
class WorldSpec:
    name: str
    start: date
    days: int
    incidents: str
    seed: int = 7
    organic_per_day: float = 1900.0
    case: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    @classmethod
    def preset(cls, name: str) -> WorldSpec:
        cfg = load_config("worlds")[name]
        start = cfg["start"] if isinstance(cfg["start"], date) else date.fromisoformat(cfg["start"])
        return cls(
            name=name,
            start=start,
            days=int(cfg["days"]),
            incidents=cfg["incidents"],
            seed=int(cfg.get("seed", 7)),
            case=cfg.get("case", {}),
            description=cfg.get("description", ""),
        )

    @property
    def t0(self) -> datetime:
        return datetime.combine(self.start, datetime.min.time(), tzinfo=UTC)

    @property
    def t_end(self) -> datetime:
        return self.t0 + timedelta(days=self.days)


def _sid(*parts: object) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()


def _day_rng(seed: int, day: date, stream: str) -> np.random.Generator:
    return np.random.default_rng(int(_sid(seed, day.isoformat(), stream)[:8], 16))


# --------------------------------------------------------------------------------------------- simulation


def _budget_fn(campaign: Campaign, incidents: list[Incident]):
    changes = sorted(
        (i.start, float(i.params["budget"]))
        for i in incidents
        if i.kind == "ads_budget_cap" and i.params.get("campaign", "1002") == campaign.id
    )

    def at(t: datetime) -> float:
        b = campaign.daily_budget
        for ts, v in changes:
            if ts <= t:
                b = v
        return b

    return at


def simulate_days(
    spec: WorldSpec, incidents: list[Incident], days: list[date]
) -> tuple[list[Journey], list[HourStats]]:
    model = WorldModel(organic_per_day=spec.organic_per_day, seed=spec.seed)
    cond = conditions_for(incidents)
    journeys: list[Journey] = []
    hours: list[HourStats] = []
    for d in days:
        d0 = datetime.combine(d, datetime.min.time(), tzinfo=UTC)
        d1 = d0 + timedelta(days=1)
        clicks: list[tuple[datetime, str]] = []
        for c in DEFAULT_CAMPAIGNS:
            hs = simulate(
                c,
                d0,
                d1,
                spent_before=0.0,
                budget_at=_budget_fn(c, incidents),
                rng=_day_rng(spec.seed, d, f"ads:{c.id}"),
            )
            hours += hs
            clicks += [(t, c.name) for h in hs for t in h.click_times]
        journeys += model.journeys(
            d0, d1, paid_clicks=clicks, conditions=cond, rng=_day_rng(spec.seed, d, "visitors")
        )
    return journeys, hours


def case_window(spec: WorldSpec, incidents: list[Incident]) -> dict[str, str]:
    causal = [i for i in incidents if i.causal]
    end = spec.t_end
    if spec.case.get("window"):
        w0 = spec.t0 + _off(spec.case["window"][0])
        w1 = spec.t0 + _off(spec.case["window"][1])
    elif causal:
        w0 = min(i.start for i in causal).replace(hour=0, minute=0, second=0, microsecond=0)
        w1 = end
    elif any(i.kind == "seasonality_only" for i in incidents):
        # Saturday and Sunday at the end of the world, compared with the weekdays just before.
        w1 = end
        while w1.weekday() != 0:
            w1 -= timedelta(days=1)
        w0 = w1 - timedelta(days=2)
    else:
        w0, w1 = end - timedelta(days=3), end
    mode = spec.case.get(
        "baseline", "preceding" if any(i.kind == "seasonality_only" for i in incidents) else "wow"
    )
    if mode == "preceding":
        span = max(w1 - w0, timedelta(days=5))
        b0, b1 = w0 - span, w0
    else:
        b0, b1 = w0 - timedelta(days=7), w1 - timedelta(days=7)
    return {
        "metric": "paid_subs",
        "window_start": w0.isoformat(),
        "window_end": w1.isoformat(),
        "baseline_start": b0.isoformat(),
        "baseline_end": b1.isoformat(),
        "baseline_mode": mode,
    }


def _off(s: str) -> timedelta:
    from simulator.schedule import parse_offset

    return parse_offset(s)


def shapley_truth(spec: WorldSpec, incidents: list[Incident], window: dict[str, str]) -> dict[str, Any]:
    """Exact Shapley shares of the window's lost paid subscriptions, over counterfactual worlds.

    v(S) = paid subscriptions in the case window when only the incidents in S happen. Every world reuses
    the same random numbers, so differences are caused by the incidents alone.
    """
    causal = [i for i in incidents if i.causal]
    w0, w1 = datetime.fromisoformat(window["window_start"]), datetime.fromisoformat(window["window_end"])
    days = [(w0 + timedelta(days=k)).date() for k in range((w1 - w0).days)]
    if not causal:
        return {"incidents": {}, "lost_paid_subs": 0.0, "counterfactual_paid_subs": None}
    cache: dict[frozenset[str], float] = {}

    def value(subset: frozenset[str]) -> float:
        if subset not in cache:
            js, _ = simulate_days(spec, [i for i in causal if i.id in subset], days)
            # Measurement-only incidents don't change real subscriptions; count real outcomes.
            cache[subset] = float(sum(j.paid_sub for j in js if w0 <= j.arrived_at < w1))
        return cache[subset]

    ids = [i.id for i in causal]
    n = len(ids)
    phi = {i: 0.0 for i in ids}
    for i in ids:
        others = [x for x in ids if x != i]
        for r in range(n):
            for combo in itertools.combinations(others, r):
                s = frozenset(combo)
                weight = math.factorial(r) * math.factorial(n - r - 1) / math.factorial(n)
                # Contribution to the *loss*: v(S) - v(S ∪ {i})
                phi[i] += weight * (value(s) - value(s | {i}))
    total = sum(phi.values())
    return {
        "counterfactual_paid_subs": value(frozenset()),
        "actual_paid_subs": value(frozenset(ids)),
        "lost_paid_subs": total,
        "incidents": {
            i: {"lost_paid_subs": round(phi[i], 3), "share": round(phi[i] / total, 4) if total > 0 else 0.0}
            for i in ids
        },
    }


# --------------------------------------------------------------------------------------------- tables


def _journey_tables(journeys: list[Journey], seed: int) -> dict[str, pl.DataFrame]:
    rng = random.Random(seed)
    viewports = {"desktop": "1440x900", "mobile": "390x844", "tablet": "820x1180"}
    ev_rows, s_rows, u_rows, p_rows = [], [], [], []
    for j in journeys:
        user_id = None
        if j.signed_up:
            user_id = "u_" + _sid(j.session_id, "user")[:16]
            u_rows.append(
                {
                    "id": user_id,
                    "created_at": next(e.ts for e in j.events if e.path == "/onboarding"),
                    "country": j.country,
                    "email": f"user{user_id[-6:]}@example.com",
                }
            )
        for k, e in enumerate(j.events):
            props = dict(e.props)
            if e.name == "signup_completed":
                props["user_id"] = user_id
            ev_rows.append(
                {
                    "event_id": f"{j.session_id}_{k}",
                    "name": e.name,
                    "ts": e.ts,
                    "session_id": j.session_id,
                    "anon_id": j.visitor_id,
                    "user_id": user_id if e.path in ("/onboarding", "/checkout") else None,
                    "path": e.path,
                    "browser": j.browser,
                    "os": j.os,
                    "device": j.device,
                    "viewport": viewports[j.device],
                    "country": j.country,
                    "channel": j.channel,
                    "props": json.dumps(props),
                }
            )
        s_rows.append(
            {
                "id": j.session_id,
                "anon_id": j.visitor_id,
                "user_id": user_id,
                "started_at": j.arrived_at,
                "last_seen_at": j.events[-1].ts,
                "browser": j.browser,
                "os": j.os,
                "device": j.device,
                "engine": j.engine,
                "country": j.country,
                "channel": j.channel,
                "utm_source": j.utm_source,
                "utm_medium": j.utm_medium,
                "utm_campaign": j.utm_campaign,
                "signup_blocked": j.signup_blocked,
                "has_replay": False,
            }
        )
        if j.checkout and j.payment_outcome:
            pay_ts = j.events[-1].ts
            card_country = j.country if rng.random() < 0.92 else "US"
            outcome_type = {"succeeded": "authorized", "declined": "issuer_declined", "error": "api_error"}[
                j.payment_outcome
            ]
            p_rows.append(
                {
                    "id": "pi_" + _sid(j.session_id, "pi")[:24],
                    "created": pay_ts,
                    "amount": 1200,
                    "currency": "usd",
                    "status": "succeeded" if j.payment_outcome == "succeeded" else "requires_payment_method",
                    "outcome_type": outcome_type,
                    "decline_code": j.decline_code if j.payment_outcome == "declined" else None,
                    "error_code": "api_error" if j.payment_outcome == "error" else None,
                    "card_brand": {"pm_card_mastercard": "mastercard", "pm_card_amex": "amex"}.get(
                        j.payment_method or "", "visa"
                    ),
                    "card_country": card_country,
                    "customer": "cus_" + _sid(user_id, "cus")[:14],
                    "metadata_country": j.country,
                    "metadata_user_id": user_id,
                }
            )
    return {
        "events": pl.DataFrame(ev_rows, infer_schema_length=None),
        "sessions": pl.DataFrame(s_rows, infer_schema_length=None),
        "users": pl.DataFrame(u_rows, infer_schema_length=None),
        "payments": pl.DataFrame(p_rows, infer_schema_length=None),
    }


def _replay_table(journeys: list[Journey], seed: int) -> pl.DataFrame:
    rng = random.Random(seed + 1)
    blocked = [j for j in journeys if j.signup_blocked]
    ok = [j for j in journeys if j.signed_up]
    abandoned = [
        j
        for j in journeys
        if any(e.name == "signup_started" for e in j.events) and not j.signed_up and not j.signup_blocked
    ]
    picks = (
        rng.sample(blocked, min(25, len(blocked)))
        + rng.sample(ok, min(15, len(ok)))
        + rng.sample(abandoned, min(8, len(abandoned)))
    )
    rows = []
    for j in picks:
        outcome = "blocked" if j.signup_blocked else "signed_up" if j.signed_up else "abandoned"
        started = next(e.ts for e in j.events if e.name == "signup_started") - timedelta(seconds=3)
        events = rrweb.recording(
            started, ACME_BASE, j.device != "desktop", outcome, random.Random(_sid(j.session_id))
        )
        rows.append(
            {
                "session_id": j.session_id,
                "started_at": started,
                "ended_at": datetime.fromtimestamp(events[-1]["timestamp"] / 1000, tz=UTC),
                "event_count": len(events),
                "events_json": json.dumps(events),
                "synthetic_recording": True,
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None)


def _deployments(spec: WorldSpec, incidents: list[Incident]) -> tuple[pl.DataFrame, pl.DataFrame]:
    rng = random.Random(spec.seed + 2)
    perm = yaml.safe_load((ROOT / "config" / "fixture_deployments.yaml").read_text())
    safari_diff = (DATA / "safari_bug.diff").read_text()
    deploys: list[dict[str, Any]] = []
    t = spec.t0 + timedelta(hours=11)
    k = 0
    while t < spec.t_end:
        msg, files = REGULAR_COMMITS[k % len(REGULAR_COMMITS)]
        deploys.append({"kind": "regular", "created_at": t, "message": msg, "files": files})
        t += timedelta(hours=rng.choice([20, 26, 30, 44, 50]))
        t = t.replace(hour=rng.randint(9, 17), minute=rng.randint(0, 59))
        k += 1
    for inc in incidents:
        if inc.kind == "deploy_bug":
            deploys.append(
                {
                    "kind": "bug",
                    "created_at": inc.start - timedelta(minutes=4),
                    "message": "refactor(signup): defer form hydration until idle",
                    "files": ["app/signup/SignupForm.tsx"],
                    "diff": safari_diff,
                    "engine": inc.params["arg"],
                }
            )
        elif inc.kind == "tracking_bug":
            deploys.append(
                {
                    "kind": "tracking",
                    "created_at": inc.start - timedelta(minutes=3),
                    "message": "chore(analytics): migrate snippet events to v2 schema",
                    "files": ["public/whydunit.js", "app/signup/SignupForm.tsx"],
                }
            )
        elif inc.kind == "harmless_deploy":
            deploys.append(
                {
                    "kind": "harmless",
                    "created_at": inc.start,
                    "message": "copy: update German pricing page translation",
                    "files": ["app/pricing/page.tsx"],
                }
            )
        elif inc.kind == "checkout_slow":
            deploys.append(
                {
                    "kind": "slow",
                    "created_at": inc.start - timedelta(minutes=5),
                    "message": "feat(checkout): validate card country server-side",
                    "files": ["app/api/checkout/route.ts"],
                }
            )
    deploys.sort(key=lambda d: d["created_at"])
    bug = next((d for d in deploys if d["kind"] == "bug"), None)
    d_rows, f_rows = [], []
    for d in deploys:
        sha = _sid(spec.seed, d["created_at"].isoformat(), d["message"])[:40]
        broken_engine = bug["engine"] if bug and d["created_at"] >= bug["created_at"] else None
        which = (
            "safari-broken"
            if broken_engine == "webkit"
            else "slow-checkout"
            if d["kind"] == "slow"
            else "healthy"
        )
        url = perm.get(which, {}).get("url") or f"https://acme-{sha[:9]}-acme-notes.vercel.app"
        did = "dpl_" + sha[:20]
        diff = d.get("diff") or _small_diff(d["message"], d["files"])
        d_rows.append(
            {
                "id": did,
                "url": url,
                "git_sha": sha,
                "git_ref": "main",
                "state": "READY",
                "created_at": d["created_at"],
                "ready_at": d["created_at"] + timedelta(seconds=rng.randint(40, 90)),
                "commit_message": d["message"],
                "files_changed": json.dumps(d["files"]),
                "diff": diff,
                "permanent_alias": which,
                "author": rng.choice(["sam@acme-notes.test", "lee@acme-notes.test", "rafa@acme-notes.test"]),
            }
        )
        for probe in PROBES:
            fails = broken_engine is not None and probe.startswith(broken_engine)
            f_rows.append(
                {
                    "deployment_id": did,
                    "flow": "signup",
                    "probe": probe,
                    "ok": not fails,
                    "ms": rng.randint(9000, 11000) if fails else rng.randint(1800, 4200),
                    "error": (
                        "Timeout 10000ms exceeded waiting for navigation to **/onboarding after clicking "
                        "'Create account'; no request to /api/signup was sent"
                    )
                    if fails
                    else None,
                    "screenshot_ref": f"fixtures/screens/signup_{'stuck' if fails else 'ok'}_{probe}.png",
                    "recorded": True,
                }
            )
    return pl.DataFrame(d_rows, infer_schema_length=None), pl.DataFrame(f_rows, infer_schema_length=None)


def _small_diff(message: str, files: list[str]) -> str:
    f = files[0]
    return (
        f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -12,7 +12,7 @@\n"
        f"-  // previous version\n+  // {message}\n"
    )


def _ads_tables(
    spec: WorldSpec, incidents: list[Incident], hours: list[HourStats]
) -> dict[str, pl.DataFrame]:
    camps = pl.DataFrame(
        [
            {
                "id": c.id,
                "name": c.name,
                "status": c.status,
                "daily_budget": _budget_fn(c, incidents)(spec.t_end),
            }
            for c in DEFAULT_CAMPAIGNS
        ]
    )
    hourly = pl.DataFrame(
        [
            {
                "campaign_id": h.campaign_id,
                "hour": h.hour,
                "impressions": h.impressions,
                "clicks": h.clicks,
                "cost": round(h.cost, 4),
                "budget_limited": h.budget_limited,
            }
            for h in hours
        ]
    )
    changes = [
        {
            "ts": spec.t0 + timedelta(days=2, hours=15, minutes=12),
            "campaign_id": "1001",
            "field": "campaign_budget.amount_micros",
            "old_value": 55.0,
            "new_value": 60.0,
            "user_email": "maria@acme-notes.test",
            "client_type": "GOOGLE_ADS_WEB_CLIENT",
        }
    ]
    for i in incidents:
        if i.kind == "ads_budget_cap":
            camp = next(c for c in DEFAULT_CAMPAIGNS if c.id == i.params.get("campaign", "1002"))
            changes.append(
                {
                    "ts": i.start,
                    "campaign_id": camp.id,
                    "field": "campaign_budget.amount_micros",
                    "old_value": camp.daily_budget,
                    "new_value": float(i.params["budget"]),
                    "user_email": "jordan@acme-notes.test",
                    "client_type": "GOOGLE_ADS_WEB_CLIENT",
                }
            )
    return {"ads_campaigns": camps, "ads_hourly": hourly, "ads_changes": pl.DataFrame(changes)}


def _voice_tables(spec: WorldSpec, journeys: list[Journey]) -> dict[str, pl.DataFrame]:
    cfg = load_config("incidents").get("voice", {})
    tickets, reviews = [], []
    by_day: dict[date, list[Journey]] = {}
    for j in journeys:
        by_day.setdefault(j.arrived_at.date(), []).append(j)
    for d in sorted(by_day):
        rng = random.Random(int(_sid(spec.seed, d, "voice")[:8], 16))
        d0 = datetime.combine(d, datetime.min.time(), tzinfo=UTC)
        msgs = voice.plan_messages((d0, d0 + timedelta(days=1)), by_day[d], cfg, rng)
        for m in msgs:
            voice._template_text(m, rng)
            if m.kind == "ticket":
                tickets.append(
                    {
                        "id": len(tickets) + 1,
                        "created_at": m.created_at,
                        "email": m.email,
                        "name": m.name,
                        "subject": m.subject,
                        "body": m.body,
                        "channel": "contact_form",
                        "meta": json.dumps(m.context),
                        "topic_truth": m.topic,
                    }
                )
            else:
                reviews.append(
                    {
                        "id": len(reviews) + 1,
                        "created_at": m.created_at,
                        "platform": m.platform,
                        "rating": m.rating,
                        "title": m.subject,
                        "body": m.body,
                        "author": m.name,
                        "topic_truth": m.topic,
                    }
                )
    return {
        "tickets": pl.DataFrame(tickets, infer_schema_length=None),
        "reviews": pl.DataFrame(reviews, infer_schema_length=None),
    }


def _world_context_tables(spec: WorldSpec, incidents: list[Incident]) -> dict[str, pl.DataFrame]:
    hol = json.loads((DATA / "holidays_2026.json").read_text())["holidays"]
    holidays = [
        h for h in hol if spec.start <= date.fromisoformat(h["date"]) < spec.start + timedelta(days=spec.days)
    ]
    news = [
        {
            "published_at": spec.t0 + timedelta(days=1, hours=9),
            "title": "Survey: hybrid teams now keep most meeting notes in shared docs",
            "url": "https://news.example.com/hybrid-notes-survey",
            "source": "news.example.com",
            "content": "A survey of 800 managers found most hybrid teams keep meeting notes in shared documents.",
            "fixture": True,
        },
        {
            "published_at": spec.t0 + timedelta(days=6, hours=14),
            "title": "Productivity software spending flat in Q3",
            "url": "https://markets.example.com/productivity-q3",
            "source": "markets.example.com",
            "content": "Spending on productivity software was flat quarter over quarter, analysts said.",
            "fixture": True,
        },
    ]
    status = [
        {
            "service": "GitHub",
            "name": "Incident with Actions",
            "impact": "minor",
            "started_at": spec.t0 + timedelta(days=3, hours=16),
            "resolved_at": spec.t0 + timedelta(days=3, hours=17),
            "url": "https://www.githubstatus.com/incidents/fixture-1",
            "fixture": True,
        },
        {
            "service": "Vercel",
            "name": "Delayed build queue in iad1",
            "impact": "minor",
            "started_at": spec.t0 + timedelta(days=8, hours=4),
            "resolved_at": spec.t0 + timedelta(days=8, hours=5),
            "url": "https://www.vercel-status.com/incidents/fixture-2",
            "fixture": True,
        },
    ]
    for i in incidents:
        if i.kind == "competitor_launch":
            name = i.params.get("arg", FIXTURE_COMPETITOR)
            news.append(
                {
                    "published_at": i.start - timedelta(hours=2),
                    "title": f"{name} launches a free tier for teams of up to 10",
                    "url": f"https://techwire.example.com/{name.lower()}-free-tier",
                    "source": "techwire.example.com",
                    "content": f"{name}, a team notes app, made its paid plan free for teams of up to ten people, "
                    "undercutting rivals that charge per member.",
                    "fixture": True,
                }
            )
        elif i.kind == "dependency_outage":
            svc = {"stripe": "Stripe"}.get(i.params.get("arg", "stripe"), i.params.get("arg"))
            status.append(
                {
                    "service": svc,
                    "name": "Elevated error rates on payment APIs",
                    "impact": "major",
                    "started_at": i.start,
                    "resolved_at": i.end,
                    "url": f"https://status.example.com/{svc.lower()}",
                    "fixture": True,
                }
            )
    return {
        "holidays": pl.DataFrame(holidays, infer_schema_length=None)
        if holidays
        else pl.DataFrame(
            schema={"date": pl.Utf8, "country": pl.Utf8, "name": pl.Utf8, "local_name": pl.Utf8}
        ),
        "news": pl.DataFrame(news),
        "status_incidents": pl.DataFrame(status),
    }


# --------------------------------------------------------------------------------------------- build


@dataclass
class WorldResult:
    path: Path
    meta: dict[str, Any]
    seconds: float
    counts: dict[str, int]


def generate(spec: WorldSpec, path: Path | None = None, *, ground_truth: bool = True) -> WorldResult:
    t_start = time.monotonic()
    incidents = parse_incidents(spec.incidents, spec.t0, spec.days)
    days = [spec.start + timedelta(days=k) for k in range(spec.days)]
    journeys, hours = simulate_days(spec, incidents, days)
    tables = _journey_tables(journeys, spec.seed)
    tables["replays"] = _replay_table(journeys, spec.seed)
    tables["deployments"], tables["flow_results"] = _deployments(spec, incidents)
    tables |= _ads_tables(spec, incidents, hours)
    tables |= _voice_tables(spec, journeys)
    tables |= _world_context_tables(spec, incidents)
    if tables["replays"].height:
        has = set(tables["replays"]["session_id"].to_list())
        tables["sessions"] = tables["sessions"].with_columns(
            pl.col("id").is_in(list(has)).alias("has_replay")
        )

    window = case_window(spec, incidents)
    meta = {
        "name": spec.name,
        "description": spec.description,
        "generator_version": GENERATOR_VERSION,
        "start": spec.t0.isoformat(),
        "end": spec.t_end.isoformat(),
        "seed": spec.seed,
        "incident_spec": spec.incidents,
        "incidents": [i.ground_truth() for i in incidents],
        "case": window,
        "truth": shapley_truth(spec, incidents, window) if ground_truth else None,
    }

    path = path or WORLDS_DIR / f"{spec.name}.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.duckdb")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        with tempfile.TemporaryDirectory(dir=path.parent) as td:
            for name, df in tables.items():
                if df.width == 0:
                    continue
                pq = Path(td) / f"{name}.parquet"
                df.write_parquet(pq)
                con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{pq}')")
        con.execute("CREATE TABLE meta (key VARCHAR PRIMARY KEY, value JSON)")
        con.execute("INSERT INTO meta VALUES ('world', ?)", [json.dumps(meta, default=str)])
    finally:
        con.close()
    tmp.replace(path)
    counts = {k: v.height for k, v in tables.items()}
    return WorldResult(path, meta, time.monotonic() - t_start, counts)


def load_meta(path: Path) -> dict[str, Any]:
    with duckdb.connect(str(path), read_only=True) as con:
        return json.loads(con.execute("SELECT value FROM meta WHERE key = 'world'").fetchone()[0])


def resolve_world(ref: str) -> Path:
    """`fixture:3inc` -> path of that world's DuckDB file, generating it on first use."""
    name = ref.removeprefix("fixture:")
    path = WORLDS_DIR / f"{name}.duckdb"
    if path.exists():
        try:
            if load_meta(path).get("generator_version") == GENERATOR_VERSION:
                return path
        except Exception:  # noqa: BLE001 - regenerate on any read problem
            pass
    return generate(WorldSpec.preset(name), path).path
