"""Per-case context shared by every detective: evidence pinning, metric registry, cached session table."""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from typing import Any

import polars as pl

from engine.analysis.data import Period, session_table
from engine.connectors import NoSource, Registry
from engine.connectors.base import TIERS, EvidenceBundle, Window
from engine.runtime import events as ev
from engine.runtime.llm import LLM, CostMeter, get_llm
from engine.runtime.schemas import Case, MetricRef
from engine.runtime.validator import Validator
from engine.settings import load_config


class CaseContext:
    def __init__(
        self,
        case: Case,
        registry: Registry,
        log: ev.CaseLog,
        llm: LLM | None = None,
        meter: CostMeter | None = None,
    ):
        self.case = case
        self.registry = registry
        self.log = log
        self.llm = llm or get_llm()
        budget = load_config("budgets")["case"]["max_cost_usd"]
        self.meter = meter or CostMeter(case.id, max_cost_usd=budget, sinks=[ev.save_llm_call])
        self.evidence: dict[str, EvidenceBundle] = {}
        self.metrics: dict[str, MetricRef] = {}
        self._sess: pl.DataFrame | None = None
        self._sess_lock = asyncio.Lock()
        self._funnel_bundle: EvidenceBundle | None = None
        self.baseline = Period(case.baseline_start, case.baseline_end)
        self.window = Period(case.window_start, case.window_end)
        self.history_start = case.history_start or min(
            case.baseline_start, case.window_start - timedelta(days=14)
        )

    @property
    def full_window(self) -> Window:
        return Window(self.history_start, self.case.window_end)

    @property
    def case_window(self) -> Window:
        return Window(self.case.baseline_start, self.case.window_end)

    # ------------------------------------------------------------------ evidence
    async def fetch(
        self, kind: str, window: Window | None, filters: dict[str, Any] | None = None, *, detective: str
    ) -> EvidenceBundle:
        try:
            bundle = await self.registry.fetch(kind, window, filters or {})
        except NoSource as e:
            await self.log.emit(
                "cannot_determine", detective, kind=kind, reason=str(e), ladder=[s.__dict__ for s in e.ladder]
            )
            await self.request_evidence(kind, detective, str(e))
            raise
        if bundle.id not in self.evidence:
            self.evidence[bundle.id] = bundle
            await ev.save_evidence(self.case.id, bundle, detective)
            await self.log.emit("evidence_pinned", detective, evidence=bundle.public())
        return bundle

    async def request_evidence(self, kind: str, detective: str, reason: str) -> None:
        """Tier 6: ask a human. The case shows an upload card for the kind and carries on without it."""
        from engine import db
        from engine.runtime.schemas import new_id

        rid = new_id("req")
        row = await db.fetchrow(
            "INSERT INTO evidence_requests (id, case_id, kind, detective, reason) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (case_id, kind) DO NOTHING RETURNING id",
            (rid, self.case.id, kind, detective, reason[:500]),
        )
        if row:
            await self.log.emit(
                "evidence_requested", detective, request={"id": rid, "kind": kind, "reason": reason[:300]}
            )

    def add_derived(self, bundle: EvidenceBundle) -> None:
        self.evidence[bundle.id] = bundle

    async def pin_derived(self, bundle: EvidenceBundle, detective: str) -> EvidenceBundle:
        if bundle.id not in self.evidence:
            self.evidence[bundle.id] = bundle
            await ev.save_evidence(self.case.id, bundle, detective)
            await self.log.emit("evidence_pinned", detective, evidence=bundle.public())
        return bundle

    async def sessions(self, detective: str) -> tuple[pl.DataFrame, EvidenceBundle]:
        """Session funnel table for the whole history (fetched once per case, shared by detectives)."""
        async with self._sess_lock:
            if self._sess is None:
                b = await self.fetch("funnel_events", self.full_window, detective=detective)
                self._sess, self._funnel_bundle = session_table(b.frame), b
        assert self._funnel_bundle is not None
        return self._sess, self._funnel_bundle

    # ------------------------------------------------------------------ metrics
    def metric(
        self,
        name: str,
        value: float,
        unit: str = "count",
        evidence_ids: list[str] | None = None,
        **detail: Any,
    ) -> MetricRef:
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:48]
        mid, k = f"m_{slug}", 2
        while mid in self.metrics and self.metrics[mid].value != value:
            mid, k = f"m_{slug}_{k}", k + 1
        ref = MetricRef(
            id=mid, name=name, value=float(value), unit=unit, evidence_ids=evidence_ids or [], detail=detail
        )
        self.metrics[mid] = ref
        return ref

    def validator(self) -> Validator:
        return Validator(self.evidence, self.metrics, {k: TIERS[b.tier][1] for k, b in self.evidence.items()})
