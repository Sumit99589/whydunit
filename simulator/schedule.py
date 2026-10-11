"""Incident schedule from config/incidents.yaml, as offsets from the simulator start."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from engine.settings import load_config

_UNITS = {"d": "days", "h": "hours", "m": "minutes"}


def parse_offset(s: str | int | float) -> timedelta:
    if isinstance(s, int | float):
        return timedelta(days=float(s))
    parts = re.findall(r"(\d+(?:\.\d+)?)([dhm])", s.strip())
    if not parts or "".join(n + u for n, u in parts) != s.strip().replace(" ", ""):
        raise ValueError(f"bad offset {s!r}; use e.g. 4d, 4d12h, 90m")
    return timedelta(**{_UNITS[u]: float(n) for n, u in parts})


@dataclass
class Incident:
    id: str
    type: str
    at: timedelta
    until: timedelta | None
    action: dict[str, Any]
    affects: dict[str, Any]
    description: str

    def starts(self, start: datetime) -> datetime:
        return start + self.at

    def ends(self, start: datetime) -> datetime | None:
        return start + self.until if self.until else None


@dataclass
class Schedule:
    tick_minutes: int
    max_tick_window: timedelta
    traffic: dict[str, Any]
    voice: dict[str, Any]
    incidents: list[Incident] = field(default_factory=list)

    def get(self, incident_id: str) -> Incident:
        return next(i for i in self.incidents if i.id == incident_id)


def load_schedule(cfg: dict[str, Any] | None = None) -> Schedule:
    cfg = cfg or load_config("incidents")
    return Schedule(
        tick_minutes=int(cfg.get("tick_minutes", 15)),
        max_tick_window=timedelta(hours=float(cfg.get("max_tick_window_hours", 3))),
        traffic=cfg.get("traffic", {}),
        voice=cfg.get("voice", {}),
        incidents=[
            Incident(
                id=i["id"],
                type=i["type"],
                at=parse_offset(i["at"]),
                until=parse_offset(i["until"]) if i.get("until") else None,
                action=i.get("action", {}),
                affects=i.get("affects", {}),
                description=" ".join(str(i.get("description", "")).split()),
            )
            for i in cfg.get("incidents", [])
        ],
    )
