"""Evidence layer: detectives ask for evidence *by kind*; a registry picks the best available connector.

Every connector returns an `EvidenceBundle` whose frame follows the kind's schema below, whatever the
source (official API, warehouse, CSV, screen reading, public web, a human upload). Each bundle records
its tier, and confidence falls with the tier.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

EvidenceKind = Literal[
    "deploys",
    "funnel_events",
    "sessions",
    "ad_performance",
    "ad_changes",
    "payments",
    "support_tickets",
    "reviews",
    "world_news",
    "holidays",
    "dependency_status",
]
KINDS: tuple[str, ...] = EvidenceKind.__args__  # type: ignore[attr-defined]

# Tier ladder (PLAN A5) and the confidence weight the lead detective gives each tier.
TIERS = {
    1: ("Official API", 1.0),
    2: ("Warehouse / PyAirbyte", 0.95),
    3: ("CSV export", 0.85),
    4: ("Screen reading", 0.6),
    5: ("Public web", 0.7),
    6: ("Provided by a human", 0.8),
}

# Columns every connector must return for each kind (extra columns are allowed).
KIND_SCHEMAS: dict[str, list[str]] = {
    "deploys": ["id", "url", "git_sha", "created_at", "commit_message", "author", "state"],
    "funnel_events": [
        "event_id",
        "ts",
        "name",
        "session_id",
        "anon_id",
        "user_id",
        "browser",
        "os",
        "device",
        "country",
        "channel",
        "path",
    ],
    "sessions": ["session_id", "started_at", "browser", "os", "device", "country", "channel", "has_replay"],
    "ad_performance": [
        "hour",
        "campaign_id",
        "campaign_name",
        "impressions",
        "clicks",
        "cost",
        "budget_limited",
    ],
    "ad_changes": ["ts", "campaign_id", "campaign_name", "field", "old_value", "new_value", "user_email"],
    "payments": [
        "id",
        "created",
        "amount",
        "currency",
        "status",
        "outcome_type",
        "decline_code",
        "card_brand",
        "card_country",
        "country",
    ],
    "support_tickets": ["id", "created_at", "subject", "body", "channel"],
    "reviews": ["id", "created_at", "platform", "rating", "title", "body"],
    "world_news": ["published_at", "title", "url", "source", "content"],
    "holidays": ["date", "country", "name"],
    "dependency_status": ["service", "name", "impact", "started_at", "resolved_at", "url"],
}


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("window bounds must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("window end must be after start")

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


class Artifact(BaseModel):
    type: Literal["screenshot", "keyframe", "diff", "link", "quote", "table", "chart"]
    ref: str | None = None  # blob key, URL or inline text
    caption: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    kind: str
    connector: str
    tier: int
    query: dict[str, Any] = Field(default_factory=dict)
    window: dict[str, str] | None = None
    data_ref: dict[str, Any] = Field(default_factory=dict)
    summary: str
    artifacts: list[Artifact] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    row_count: int = 0
    sample: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    frame: pl.DataFrame | None = Field(default=None, exclude=True)

    @property
    def tier_label(self) -> str:
        return TIERS[self.tier][0]

    @property
    def confidence(self) -> float:
        return TIERS[self.tier][1]

    def public(self) -> dict[str, Any]:
        d = self.model_dump(mode="json")
        d["tier_label"], d["confidence"] = self.tier_label, self.confidence
        return d


def evidence_id(kind: str, connector: str, query: dict[str, Any], window: Window | None) -> str:
    blob = json.dumps(
        {"k": kind, "c": connector, "q": query, "w": window.as_dict() if window else None},
        sort_keys=True,
        default=str,
    )
    return f"ev_{kind[:4]}_{hashlib.sha1(blob.encode()).hexdigest()[:10]}"


def make_bundle(
    kind: str,
    connector: Connector,
    frame: pl.DataFrame,
    window: Window | None,
    *,
    query: dict[str, Any] | None = None,
    summary: str,
    artifacts: list[Artifact] | None = None,
    data_ref: dict[str, Any] | None = None,
    notes: list[str] | None = None,
    sample_size: int = 8,
    tier: int | None = None,
) -> EvidenceBundle:
    missing = [c for c in KIND_SCHEMAS.get(kind, []) if c not in frame.columns]
    if missing:
        raise ValueError(f"{connector.name} returned {kind} without columns {missing}")
    q = query or {}
    return EvidenceBundle(
        id=evidence_id(kind, connector.name, q, window),
        kind=kind,
        connector=connector.name,
        tier=tier if tier is not None else getattr(connector, "tier_for", lambda k: connector.tier)(kind),
        query=q,
        window=window.as_dict() if window else None,
        data_ref=data_ref or {},
        summary=summary,
        artifacts=artifacts or [],
        row_count=frame.height,
        sample=[
            {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()}
            for r in frame.head(sample_size).to_dicts()
        ],
        notes=notes or [],
        frame=frame,
    )


class ConnectorUnavailable(RuntimeError):
    pass


@runtime_checkable
class Connector(Protocol):
    name: str
    tier: int
    kinds: tuple[str, ...]

    async def available(self) -> bool: ...

    async def fetch(
        self, kind: str, window: Window | None, filters: dict[str, Any] | None = None
    ) -> EvidenceBundle: ...


class BaseConnector:
    """Convenience base: subclasses implement `_fetch_<kind>` methods returning EvidenceBundles."""

    name: ClassVar[str] = "base"
    tier: ClassVar[int] = 1
    kinds: ClassVar[tuple[str, ...]] = ()
    needs_env: ClassVar[tuple[str, ...]] = ()

    async def available(self) -> bool:
        from engine.settings import has_env

        return has_env(*self.needs_env)

    async def fetch(
        self, kind: str, window: Window | None, filters: dict[str, Any] | None = None
    ) -> EvidenceBundle:
        if kind not in self.kinds:
            raise ValueError(f"{self.name} does not provide {kind}")
        fn = getattr(self, f"_fetch_{kind}")
        return await fn(window, filters or {})

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tier": self.tier,
            "tier_label": TIERS[self.tier][0],
            "kinds": list(self.kinds),
            "needs": list(self.needs_env),
        }


def empty_frame(kind: str) -> pl.DataFrame:
    return pl.DataFrame({c: [] for c in KIND_SCHEMAS[kind]})
