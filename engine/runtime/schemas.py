"""Pydantic schemas for cases, findings, hypotheses, reports and cross-examination."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CaseStatus = Literal["investigating", "verdict", "fixing", "verifying", "closed", "failed"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Case(BaseModel):
    id: str = Field(default_factory=lambda: new_id("case"))
    world: str  # "live" or "fixture:<name>"
    metric: str = "paid_subs"
    question: str = "Why did new paid subscriptions fall?"
    window_start: datetime
    window_end: datetime
    baseline_start: datetime
    baseline_end: datetime
    history_start: datetime | None = None
    status: CaseStatus = "investigating"
    auto_opened: bool = False
    project_id: str | None = "acme"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MetricRef(BaseModel):
    """A number computed by code. Narrative numbers must match one of these."""

    id: str
    name: str
    value: float
    unit: Literal["count", "per_day", "rate", "pct_change", "share", "z", "currency", "hours"] = "count"
    evidence_ids: list[str] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: new_id("f"))
    detective: str = ""
    claim: str
    kind: Literal["observed", "inference"] = "observed"
    evidence_ids: list[str] = Field(default_factory=list)
    metrics_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0, le=1)
    status: Literal["accepted", "suspicion", "rejected"] = "accepted"
    rejection_reason: str | None = None


class EffectSpec(BaseModel):
    """What a hypothesis would change, so it can be attributed: factor + segment + start time."""

    factor: Literal["traffic", "signup_rate", "checkout_rate", "payment_success_rate"]
    segment: dict[str, Any] = Field(default_factory=dict)
    start: datetime | None = None
    end: datetime | None = None


class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: new_id("h"))
    statement: str
    effect: EffectSpec
    proposed_by: str = ""
    supporting: list[str] = Field(default_factory=list)  # finding ids
    contradicting: list[str] = Field(default_factory=list)
    mechanism_evidence: list[str] = Field(default_factory=list)
    timing_evidence: list[str] = Field(default_factory=list)
    status: Literal["open", "supported", "rejected", "inconclusive"] = "open"
    reason: str = ""


class CannotDetermine(BaseModel):
    kind: str
    reason: str
    tried: list[str] = Field(default_factory=list)


class DetectiveReport(BaseModel):
    detective: str
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    suspicions: list[Finding] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    cannot_determine: list[CannotDetermine] = Field(default_factory=list)
    checked: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    model_mode: Literal["llm", "deterministic"] = "deterministic"
    notes: list[str] = Field(default_factory=list)


class Question(BaseModel):
    id: str = Field(default_factory=lambda: new_id("q"))
    to: str
    text: str
    kind: str = "free"  # structured check: before_after, external_release, deploy_around, ...
    params: dict[str, Any] = Field(default_factory=dict)
    about_hypothesis: str | None = None
    round: int = 1


class Answer(BaseModel):
    question_id: str
    detective: str
    text: str
    findings: list[Finding] = Field(default_factory=list)
    cannot_determine: CannotDetermine | None = None
    verdict: Literal["supports", "contradicts", "neutral", "cannot_determine"] = "neutral"
