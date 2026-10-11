"""The Acme world model, shared by the live simulator (Stage 3) and back-dated fixture worlds (Stage 4).

It turns *conditions* (browser health, paid clicks, decline rates, holidays…) into synthetic visitor
journeys: who arrives when, from which segment, and how far down the funnel they get. The simulator
replays journeys against real systems; fixture worlds write them straight into tables.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

# ---------------------------------------------------------------------------------------------
# Segment mix
# ---------------------------------------------------------------------------------------------

# (device, os, browser, engine, weight). "engine" decides which health probe applies: every
# browser on iOS/iPadOS is WebKit, so a WebKit bug hits iPhone Chrome users too.
PLATFORMS: list[tuple[str, str, str, str, float]] = [
    ("desktop", "Windows", "Chrome", "chromium", 0.22),
    ("desktop", "macOS", "Chrome", "chromium", 0.10),
    ("desktop", "Linux", "Chrome", "chromium", 0.03),
    ("desktop", "macOS", "Safari", "webkit", 0.08),
    ("desktop", "Windows", "Edge", "chromium", 0.06),
    ("desktop", "Windows", "Firefox", "firefox", 0.04),
    ("desktop", "Linux", "Firefox", "firefox", 0.02),
    ("mobile", "iOS", "Safari", "webkit", 0.19),
    ("mobile", "iOS", "Chrome", "webkit", 0.03),
    ("mobile", "Android", "Chrome", "chromium", 0.15),
    ("mobile", "Android", "Samsung Internet", "chromium", 0.03),
    ("tablet", "iPadOS", "Safari", "webkit", 0.05),
]

COUNTRIES: list[tuple[str, float]] = [
    ("US", 0.38),
    ("GB", 0.12),
    ("IN", 0.14),
    ("DE", 0.10),
    ("BR", 0.12),
    ("CA", 0.07),
    ("FR", 0.07),
]

# Hour-of-day traffic weights (UTC). Peaks in the US/EU overlap.
HOURLY = np.array(
    [
        0.45,
        0.40,
        0.35,
        0.33,
        0.35,
        0.45,
        0.60,
        0.80,
        0.95,
        1.05,
        1.15,
        1.25,
        1.35,
        1.45,
        1.55,
        1.55,
        1.50,
        1.40,
        1.30,
        1.15,
        1.00,
        0.85,
        0.70,
        0.55,
    ]
)
HOURLY = HOURLY / HOURLY.mean()
WEEKDAY = np.array([1.05, 1.10, 1.10, 1.08, 1.00, 0.80, 0.75])  # Mon..Sun
WEEKDAY = WEEKDAY / WEEKDAY.mean()


def probe_for(engine: str, device: str) -> str:
    """Map a visitor platform to the browser-matrix probe that decides whether signup works."""
    if engine == "webkit":
        return "webkit-mobile" if device in ("mobile", "tablet") else "webkit-desktop"
    if engine == "firefox":
        return "firefox-desktop"
    return "chromium-mobile" if device == "mobile" else "chromium-desktop"


PROBES = ("chromium-desktop", "webkit-desktop", "webkit-mobile", "chromium-mobile", "firefox-desktop")


@dataclass
class FunnelRates:
    start_signup: dict[str, float] = field(
        default_factory=lambda: {"desktop": 0.17, "mobile": 0.13, "tablet": 0.15}
    )
    paid_start_multiplier: float = 1.15
    complete_signup: float = 0.62
    start_checkout: float = 0.36
    base_decline_rate: float = 0.03
    error_rate: float = 0.004
    pricing_view: float = 0.35


DECLINE_CODES_BASE = [("generic_decline", 0.5), ("insufficient_funds", 0.35), ("expired_card", 0.15)]
DECLINE_CODES_ISSUER = [("generic_decline", 0.35), ("insufficient_funds", 0.2), ("do_not_honor", 0.45)]

# Stripe test PaymentMethods that produce each outcome for real (simulator) payments.
PM_FOR_DECLINE = {
    "generic_decline": "pm_card_chargeDeclined",
    "insufficient_funds": "pm_card_chargeDeclinedInsufficientFunds",
    "expired_card": "pm_card_chargeDeclinedExpiredCard",
    "do_not_honor": "pm_card_chargeDeclined",
    "lost_card": "pm_card_chargeDeclinedLostCard",
    "processing_error": "pm_card_chargeDeclinedProcessingError",
}
PM_SUCCESS = ["pm_card_visa", "pm_card_visa", "pm_card_mastercard", "pm_card_amex"]


# ---------------------------------------------------------------------------------------------
# Conditions: what the world looks like at a moment. Incidents are functions that modify them.
# ---------------------------------------------------------------------------------------------


@dataclass
class Conditions:
    """Multipliers and switches in effect at a given time, for a given segment."""

    signup_ok: dict[str, bool] = field(default_factory=lambda: {p: True for p in PROBES})
    traffic_mult: float = 1.0
    country_traffic_mult: dict[str, float] = field(default_factory=dict)
    start_signup_mult: float = 1.0
    checkout_mult: float = 1.0
    decline_rate_by_country: dict[str, float] = field(default_factory=dict)
    extra_error_rate: float = 0.0
    track_signup_completed: bool = True
    checkout_slow: bool = False


ConditionFn = Callable[[datetime, Conditions], None]


@dataclass
class Event:
    name: str
    ts: datetime
    props: dict = field(default_factory=dict)
    path: str = "/"


@dataclass
class Journey:
    visitor_id: str
    session_id: str
    arrived_at: datetime
    device: str
    os: str
    browser: str
    engine: str
    country: str
    channel: str
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    events: list[Event] = field(default_factory=list)
    signed_up: bool = False
    signup_blocked: bool = False  # tried to sign up but the product was broken for them
    checkout: bool = False
    payment_outcome: str | None = None  # succeeded | declined | error
    decline_code: str | None = None
    payment_method: str | None = None
    tracked_completed: bool = True

    @property
    def probe(self) -> str:
        return probe_for(self.engine, self.device)

    @property
    def paid_sub(self) -> bool:
        return self.payment_outcome == "succeeded"


def _stable_id(prefix: str, *parts: object) -> str:
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:20]
    return f"{prefix}_{h}"


@dataclass
class WorldModel:
    organic_per_day: float = 1900.0  # organic + referral visitors per day (before curves)
    referral_share: float = 0.22
    rates: FunnelRates = field(default_factory=FunnelRates)
    noise_sd: float = 0.06  # day-level multiplicative noise on traffic
    seed: int = 7

    def expected_unpaid_visitors(self, start: datetime, end: datetime) -> float:
        """Expected organic+referral arrivals in [start, end) from the daily/weekly curve."""
        total, t = 0.0, start
        while t < end:
            nxt = min(end, (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
            frac = (nxt - t).total_seconds() / 86400.0
            total += self.organic_per_day * frac * HOURLY[t.hour] * WEEKDAY[t.weekday()]
            t = nxt
        return total

    def day_noise(self, day: datetime) -> float:
        digest = hashlib.sha1(f"{self.seed}|{day.date().isoformat()}".encode()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:4], "big"))
        return float(math.exp(rng.normal(0, self.noise_sd)))

    def journeys(
        self,
        start: datetime,
        end: datetime,
        *,
        paid_clicks: list[tuple[datetime, str]] | None = None,
        conditions: Callable[[datetime], Conditions] | None = None,
        rng: np.random.Generator | None = None,
    ) -> list[Journey]:
        """Generate visitor journeys arriving in [start, end).

        `paid_clicks` lists (timestamp, campaign) for each paid arrival (from the ads platform);
        `conditions(t)` gives the incident-adjusted conditions at time t.
        """
        rng = rng or np.random.default_rng(self.seed)
        cond_at = conditions or (lambda t: Conditions())
        arrivals: list[tuple[datetime, str, str | None, str | None, str | None]] = []

        # Unpaid arrivals, hour by hour (Poisson around the curve, with daily noise).
        t = start
        while t < end:
            nxt = min(end, (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
            c = cond_at(t)
            lam = self.expected_unpaid_visitors(t, nxt) * self.day_noise(t) * c.traffic_mult
            n = int(rng.poisson(max(lam, 0.0)))
            span = (nxt - t).total_seconds()
            for _ in range(n):
                ts = t + timedelta(seconds=float(rng.uniform(0, span)))
                if rng.random() < self.referral_share:
                    src = str(
                        rng.choice(["news.ycombinator.com", "producthunt.com", "reddit.com", "twitter.com"])
                    )
                    arrivals.append((ts, "referral", src, "referral", None))
                else:
                    arrivals.append((ts, "organic", None, None, None))
            t = nxt
        for ts, campaign in paid_clicks or []:
            if start <= ts < end:
                arrivals.append((ts, "paid", "google", "cpc", campaign))
        arrivals.sort(key=lambda a: a[0])

        plat_w = np.array([p[4] for p in PLATFORMS])
        plat_w = plat_w / plat_w.sum()
        ctry_w = np.array([c[1] for c in COUNTRIES])
        ctry_w = ctry_w / ctry_w.sum()

        out: list[Journey] = []
        for i, (ts, channel, src, medium, campaign) in enumerate(arrivals):
            c = cond_at(ts)
            device, os_, browser, engine, _ = PLATFORMS[int(rng.choice(len(PLATFORMS), p=plat_w))]
            country = COUNTRIES[int(rng.choice(len(COUNTRIES), p=ctry_w))][0]
            # Country-specific traffic drops (holidays) thin arrivals from that country.
            keep = c.country_traffic_mult.get(country, 1.0)
            if keep < 1.0 and rng.random() > keep:
                continue
            vid = _stable_id("a", self.seed, ts.isoformat(), i)
            j = Journey(
                visitor_id=vid,
                session_id=_stable_id("s", self.seed, ts.isoformat(), i),
                arrived_at=ts,
                device=device,
                os=os_,
                browser=browser,
                engine=engine,
                country=country,
                channel=channel,
                utm_source=src,
                utm_medium=medium,
                utm_campaign=campaign,
            )
            self._walk(j, c, rng)
            out.append(j)
        return out

    def _walk(self, j: Journey, c: Conditions, rng: np.random.Generator) -> None:
        r = self.rates
        t = j.arrived_at
        j.events.append(Event("page_view", t, {"title": "Acme Notes"}, "/"))
        if rng.random() < r.pricing_view:
            t += timedelta(seconds=float(rng.uniform(15, 90)))
            j.events.append(Event("page_view", t, {"title": "Pricing"}, "/pricing"))
        p_start = r.start_signup[j.device] * c.start_signup_mult
        if j.channel == "paid":
            p_start *= r.paid_start_multiplier
        if rng.random() >= p_start:
            return
        t += timedelta(seconds=float(rng.uniform(20, 150)))
        j.events.append(Event("page_view", t, {"title": "Sign up"}, "/signup"))
        t += timedelta(seconds=float(rng.uniform(5, 40)))
        j.events.append(Event("signup_started", t, {"form": "signup"}, "/signup"))
        if rng.random() >= r.complete_signup:
            return
        if not c.signup_ok.get(j.probe, True):
            j.signup_blocked = True
            return
        t += timedelta(seconds=float(rng.uniform(15, 60)))
        j.signed_up = True
        j.tracked_completed = c.track_signup_completed
        if c.track_signup_completed:
            j.events.append(Event("signup_completed", t, {}, "/signup"))
        t += timedelta(seconds=float(rng.uniform(2, 6)))
        j.events.append(Event("page_view", t, {"title": "Welcome"}, "/onboarding"))
        if rng.random() >= r.start_checkout * c.checkout_mult:
            return
        t += timedelta(seconds=float(rng.uniform(40, 400)))
        j.checkout = True
        j.events.append(Event("page_view", t, {"title": "Checkout"}, "/checkout"))
        j.events.append(
            Event(
                "checkout_started",
                t + timedelta(seconds=1),
                {"plan": "pro", "amount_cents": 1200},
                "/checkout",
            )
        )
        t += timedelta(seconds=float(rng.uniform(25, 120)) * (6 if c.checkout_slow else 1))
        decline_rate = c.decline_rate_by_country.get(j.country, r.base_decline_rate)
        u = rng.random()
        if u < r.error_rate + c.extra_error_rate:
            j.payment_outcome, j.decline_code = "error", "api_error"
            j.payment_method = "pm_card_visa"
        elif u < r.error_rate + c.extra_error_rate + decline_rate:
            issuer = j.country in c.decline_rate_by_country
            codes = DECLINE_CODES_ISSUER if issuer else DECLINE_CODES_BASE
            names, w = zip(*codes, strict=True)
            code = str(rng.choice(names, p=np.array(w) / sum(w)))
            j.payment_outcome, j.decline_code = "declined", code
            j.payment_method = PM_FOR_DECLINE[code]
        else:
            j.payment_outcome = "succeeded"
            j.payment_method = str(rng.choice(PM_SUCCESS))
        if j.payment_outcome == "succeeded":
            j.events.append(Event("payment_succeeded", t, {"plan": "pro", "amount_cents": 1200}, "/checkout"))
        else:
            j.events.append(Event("payment_failed", t, {"decline_code": j.decline_code}, "/checkout"))
