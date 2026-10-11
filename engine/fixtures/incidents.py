"""Incident library for fixture worlds. Each incident has a parameterised effect and its ground truth.

An incident changes the world in two ways: it modifies `Conditions` while active (what visitors
experience), and it leaves artifacts in source systems (a deployment, an ads change event, a holiday,
a status-page incident, a news article). Detectives see only the artifacts and the data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from engine.world.model import PROBES, Conditions

ENGINE_PROBES = {
    "webkit": ["webkit-desktop", "webkit-mobile"],
    "chromium": ["chromium-desktop", "chromium-mobile"],
    "firefox": ["firefox-desktop"],
    "mobile": ["webkit-mobile", "chromium-mobile"],
}

# Fictional competitor so fixture "news" never invents claims about a real company.
FIXTURE_COMPETITOR = "Quillboard"


@dataclass
class Incident:
    kind: str
    start: datetime
    params: dict[str, Any] = field(default_factory=dict)
    end: datetime | None = None

    @property
    def id(self) -> str:
        arg = self.params.get("arg")
        return f"{self.kind}:{arg}" if arg else self.kind

    def active(self, t: datetime) -> bool:
        return t >= self.start and (self.end is None or t < self.end)

    # Whether this incident changes the headline metric at all (red herrings do not).
    @property
    def causal(self) -> bool:
        return self.kind not in ("harmless_deploy", "seasonality_only", "noise_only")

    def apply(self, t: datetime, c: Conditions) -> None:
        if not self.active(t):
            return
        k, p = self.kind, self.params
        if k == "deploy_bug":
            for probe in ENGINE_PROBES[p.get("arg", "webkit")]:
                c.signup_ok[probe] = False
        elif k == "payment_declines":
            c.decline_rate_by_country[p.get("arg", "BR")] = float(p.get("rate", 0.45))
        elif k == "public_holiday":
            if t.date() == self.start.date():
                c.country_traffic_mult[p.get("arg", "DE")] = float(p.get("traffic", 0.35))
        elif k == "dependency_outage":
            c.extra_error_rate += float(p.get("error_rate", 0.6))
        elif k == "competitor_launch":
            c.start_signup_mult *= float(p.get("signup_mult", 0.82))
        elif k == "tracking_bug":
            c.track_signup_completed = False
        elif k == "checkout_slow":
            c.checkout_slow = True
            c.checkout_mult *= float(p.get("checkout_mult", 0.8))

    def ground_truth(self) -> dict[str, Any]:
        k, p = self.kind, self.params
        affects: dict[str, Any] = {
            "deploy_bug": {"factor": "signup_rate", "segment": {"engine": p.get("arg", "webkit")}},
            "ads_budget_cap": {"factor": "traffic", "segment": {"channel": "paid"}},
            "payment_declines": {
                "factor": "payment_success_rate",
                "segment": {"country": p.get("arg", "BR")},
            },
            "public_holiday": {"factor": "traffic", "segment": {"country": p.get("arg", "DE")}},
            "dependency_outage": {"factor": "payment_success_rate", "segment": {}},
            "competitor_launch": {"factor": "signup_rate", "segment": {}},
            "tracking_bug": {"factor": "signup_rate", "segment": {}, "measurement_only": True},
            "checkout_slow": {"factor": "checkout_rate", "segment": {}},
        }.get(k, {})
        return {
            "id": self.id,
            "kind": k,
            "params": p,
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end else None,
            "causal": self.causal,
            "affects": affects,
        }


DEFAULTS: dict[str, dict[str, Any]] = {
    "deploy_bug": {"arg": "webkit"},
    "ads_budget_cap": {"campaign": "1002", "budget": 150.0},
    "payment_declines": {"arg": "BR", "rate": 0.45},
    "public_holiday": {"arg": "DE", "traffic": 0.35},
    "dependency_outage": {"arg": "stripe", "hours": 6, "error_rate": 0.6},
    "competitor_launch": {"arg": FIXTURE_COMPETITOR, "signup_mult": 0.82},
    "tracking_bug": {},
    "seasonality_only": {},
    "noise_only": {},
    "harmless_deploy": {},
    "checkout_slow": {"checkout_mult": 0.8},
}


def parse_offset(s: str) -> timedelta:
    from simulator.schedule import parse_offset as p

    return p(s)


def parse_incidents(spec: str, world_start: datetime, days: int) -> list[Incident]:
    """Parse `deploy_bug:webkit@10d,ads_budget_cap,payment_declines:BR` into incidents.

    Without an `@offset`, incidents start at sensible defaults near the end of the world, so the last
    few days form the case window.
    """
    default_offsets = {
        "deploy_bug": timedelta(days=days - 4, hours=10),
        "ads_budget_cap": timedelta(days=days - 4, hours=21),
        "payment_declines": timedelta(days=days - 4, hours=14),
        "public_holiday": timedelta(days=days - 2),
        "dependency_outage": timedelta(days=days - 3, hours=13),
        "competitor_launch": timedelta(days=days - 4, hours=14),
        "tracking_bug": timedelta(days=days - 3, hours=11),
        "harmless_deploy": timedelta(days=days - 2, hours=9, minutes=30),
        "checkout_slow": timedelta(days=days - 3, hours=10),
        "seasonality_only": timedelta(days=days - 2),
        "noise_only": timedelta(days=days - 3),
    }
    out: list[Incident] = []
    for raw in filter(None, (s.strip() for s in spec.split(","))):
        body, _, at = raw.partition("@")
        kind, *args = body.split(":")
        if kind not in DEFAULTS:
            raise ValueError(f"unknown incident {kind!r}; known: {', '.join(DEFAULTS)}")
        params = dict(DEFAULTS[kind])
        for a in args:
            if "=" in a:
                k, v = a.split("=", 1)
                params[k] = _num(v)
            else:
                params["arg"] = a
        start = world_start + (parse_offset(at) if at else default_offsets[kind])
        if kind == "public_holiday" and not at:
            start = start.replace(hour=0, minute=0)
        end = None
        if kind == "dependency_outage" or "hours" in params:
            # Any incident can be given a duration (e.g. a bug that is fixed after 48 hours).
            end = start + timedelta(hours=float(params.get("hours", 6)))
        out.append(Incident(kind, start, params, end))
    return out


def _num(v: str) -> Any:
    try:
        return float(v) if "." in v else int(v)
    except ValueError:
        return v


def conditions_for(incidents: list[Incident]):
    active = [i for i in incidents if i.causal]

    def at(t: datetime) -> Conditions:
        c = Conditions(signup_ok={p: True for p in PROBES})
        for inc in active:
            inc.apply(t, c)
        return c

    return at
