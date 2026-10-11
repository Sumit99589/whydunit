"""Detective base: deterministic playbook, optional Nemotron tool loop, validated report.

Every detective first runs its playbook: the standard checks, all computed by code, each pinning evidence
and registering metrics. When Token Factory is configured, Nano then drives a short tool-calling loop to
look further, and Super writes the final report as strict JSON. The validator checks every finding;
rejected ones get one re-prompt with the reason, and a second failure turns them into "suspicions".
Without a key (or if a model call fails), the playbook's templated findings are the report.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from engine.connectors import NoSource
from engine.connectors.base import EvidenceBundle, Window, evidence_id, make_bundle
from engine.runtime import events as ev
from engine.runtime.context import CaseContext
from engine.runtime.llm import BudgetExceeded, LLMUnavailable
from engine.runtime.schemas import (
    Answer,
    CannotDetermine,
    DetectiveReport,
    EffectSpec,
    Finding,
    Hypothesis,
    Question,
)
from engine.settings import load_config

log = logging.getLogger("whydunit.agents")

SEGMENT_LABELS = {
    ("engine", "webkit"): "WebKit (Safari and every iOS browser)",
    ("engine", "chromium"): "Chromium browsers (Chrome, Edge, Samsung)",
    ("engine", "firefox"): "Firefox",
    ("channel", "paid"): "paid traffic",
    ("channel", "organic"): "organic traffic",
    ("channel", "referral"): "referral traffic",
}
COUNTRY = {
    "US": "the US",
    "GB": "the UK",
    "IN": "India",
    "DE": "Germany",
    "BR": "Brazil",
    "CA": "Canada",
    "FR": "France",
}


def seg_label(dim: str, value: Any) -> str:
    if (dim, value) in SEGMENT_LABELS:
        return SEGMENT_LABELS[(dim, value)]
    if dim == "country":
        return COUNTRY.get(value, value)
    return f"{value} ({dim})"


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%"


@dataclass
class AnalysisSource:
    """Evidence computed by Whydunit's own analysis code; it inherits the weakest tier of its sources."""

    tier: int = 1
    name: str = "whydunit-analysis"
    kinds: tuple[str, ...] = ()


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Awaitable[dict[str, Any]]]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


@dataclass
class Detective:
    ctx: CaseContext
    name: str = "detective"
    title: str = "Detective"
    mission: str = ""
    findings: list[Finding] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    cannot: list[CannotDetermine] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- helpers for subclasses
    async def emit(self, type: str, **payload: Any) -> None:
        await self.ctx.log.emit(type, self.name, **payload)

    async def fetch(
        self, kind: str, window: Window | None, filters: dict[str, Any] | None = None
    ) -> EvidenceBundle | None:
        try:
            b = await self.ctx.fetch(kind, window, filters, detective=self.name)
            self.checked.append(f"{kind} via {b.connector} (tier {b.tier})")
            return b
        except NoSource as e:
            self.cannot.append(
                CannotDetermine(
                    kind=kind, reason=str(e), tried=[f"{s.connector} (tier {s.tier})" for s in e.ladder]
                )
            )
            return None

    async def analysis(
        self,
        name: str,
        rows: list[dict[str, Any]] | pl.DataFrame,
        summary: str,
        sources: list[str],
        window: Window | None = None,
        **meta: Any,
    ) -> EvidenceBundle:
        """Pin a code-computed analysis result as evidence (derived from the cited source evidence)."""
        df = (
            rows
            if isinstance(rows, pl.DataFrame)
            else pl.DataFrame(rows, infer_schema_length=None)
            if rows
            else pl.DataFrame()
        )

        tier = min((self.ctx.evidence[s].tier for s in sources if s in self.ctx.evidence), default=1)
        b = make_bundle(
            f"analysis:{name}",
            AnalysisSource(tier),
            df,
            window,
            query={"sources": sources, **meta},
            summary=summary,
            data_ref={"derived_from": sources, "computed_by": "engine.analysis"},
        )
        b.id = evidence_id(f"analysis:{name}", "whydunit-analysis", {"s": sources, **meta}, window)
        return await self.ctx.pin_derived(b, self.name)

    def add_finding(
        self,
        claim: str,
        evidence: list[str],
        metrics: list[str],
        kind: str = "observed",
        confidence: float = 0.9,
    ) -> Finding:
        f = Finding(
            detective=self.name,
            claim=claim,
            kind=kind,
            evidence_ids=evidence,
            metrics_refs=metrics,  # type: ignore[arg-type]
            confidence=confidence,
        )
        self.findings.append(f)
        return f

    def propose(
        self,
        statement: str,
        factor: str,
        segment: dict[str, Any],
        start: Any,
        support: list[str],
        end: Any = None,
    ) -> Hypothesis:
        # By default a hypothesis rests on the finding the detective has just made.
        support = support or ([self.findings[-1].id] if self.findings else [])
        h = Hypothesis(
            statement=statement,
            effect=EffectSpec(factor=factor, segment=segment, start=start, end=end),  # type: ignore[arg-type]
            proposed_by=self.name,
            supporting=support,
        )
        self.hypotheses.append(h)
        return h

    # ---------------------------------------------------------------- to implement
    async def playbook(self) -> None:
        raise NotImplementedError

    async def answer(self, q: Question) -> Answer:
        """Answer the lead's question with new evidence, or say cannot_determine."""
        handler = getattr(self, f"answer_{q.kind}", None)
        if handler is None:
            return Answer(
                question_id=q.id,
                detective=self.name,
                text="I have no way to check that.",
                verdict="cannot_determine",
                cannot_determine=CannotDetermine(kind=q.kind, reason=f"{self.name} has no {q.kind} check"),
            )
        try:
            return await handler(q)
        except Exception as e:  # noqa: BLE001 - an unanswerable question is an honest answer, not a crash
            return Answer(
                question_id=q.id,
                detective=self.name,
                text=f"Could not check: {type(e).__name__}.",
                verdict="cannot_determine",
                cannot_determine=CannotDetermine(kind=q.kind, reason=str(e)[:200]),
            )

    async def validated(self, f: Finding) -> Finding:
        """Validate one answer finding (no re-prompt) and record it."""
        acc, sus = await self.validate([f], reprompt=False)
        return (acc or sus)[0]

    def tools(self) -> list[Tool]:
        return []

    # ---------------------------------------------------------------- run
    async def run(self) -> DetectiveReport:
        t0 = time.monotonic()
        await self.emit("detective_started", title=self.title, mission=self.mission)
        cost0 = self.ctx.meter.cost_usd
        mode = "deterministic"
        try:
            await self.playbook()
        except Exception as e:  # noqa: BLE001 - a detective failing must not sink the case
            log.exception("%s playbook failed", self.name)
            self.notes.append(f"playbook error: {type(e).__name__}: {e}")
            await self.emit("detective_error", error=f"{type(e).__name__}: {e}"[:300])
        findings = self.findings
        summary = self.template_summary()
        if self.ctx.llm.available() and self.tools() is not None:
            try:
                findings, summary = await self.llm_investigate()
                mode = "llm"
            except (LLMUnavailable, BudgetExceeded) as e:
                self.notes.append(f"model unavailable, using computed findings: {e}")
            except Exception as e:  # noqa: BLE001
                log.exception("%s LLM loop failed", self.name)
                self.notes.append(f"model step failed ({type(e).__name__}); using computed findings")
        accepted, suspicions = await self.validate(findings)
        report = DetectiveReport(
            detective=self.name,
            summary=summary,
            findings=accepted,
            suspicions=suspicions,
            hypotheses=self.hypotheses,
            cannot_determine=self.cannot,
            checked=self.checked,
            cost_usd=round(self.ctx.meter.cost_usd - cost0, 6),
            model_mode=mode,  # type: ignore[arg-type]
            notes=self.notes,
        )
        for h in self.hypotheses:
            await ev.save_hypothesis(self.ctx.case.id, h)
        await self.emit(
            "detective_report", report=report.model_dump(mode="json"), seconds=round(time.monotonic() - t0, 2)
        )
        return report

    async def validate(
        self, findings: list[Finding], *, reprompt: bool = True
    ) -> tuple[list[Finding], list[Finding]]:
        v = self.ctx.validator()
        accepted, suspicions = [], []
        for f in findings:
            f.detective = self.name
            checked = v.apply(f)
            if checked.status == "rejected" and reprompt and self.ctx.llm.available():
                fixed = await self.fix_finding(checked)
                if fixed is not None:
                    checked = v.apply(fixed.model_copy(update={"id": f.id, "detective": self.name}))
            if checked.status == "rejected":
                checked = checked.model_copy(update={"status": "suspicion"})
                suspicions.append(checked)
                await self.emit("finding_rejected", finding=checked.model_dump(mode="json"))
            else:
                accepted.append(checked)
                await self.emit("finding", finding=checked.model_dump(mode="json"))
            await ev.save_finding(self.ctx.case.id, checked)
        return accepted, suspicions

    def template_summary(self) -> str:
        if not self.findings:
            return f"{self.title}: nothing conclusive." + (" " + self.cannot[0].reason if self.cannot else "")
        return self.findings[0].claim

    # ---------------------------------------------------------------- the model path
    def catalogue(self) -> str:
        ev_lines = [
            f"- {e.id} [{e.kind}, {e.connector}, tier {e.tier}]: {e.summary[:180]}"
            for e in self.ctx.evidence.values()
        ]
        m_lines = [f"- {m.id} = {m.value:.6g} ({m.unit}) — {m.name}" for m in self.ctx.metrics.values()]
        return (
            "EVIDENCE\n"
            + "\n".join(ev_lines[-40:])
            + "\n\nMETRICS (computed by code)\n"
            + "\n".join(m_lines[-80:])
        )

    def system_prompt(self) -> str:
        return (
            f"You are the {self.title} in Whydunit, a team of detectives investigating why a business metric "
            f"changed for Acme Notes (a team note-taking SaaS). {self.mission}\n"
            "Rules: every claim must cite evidence ids that exist; every number you write must be one of the "
            "computed metrics you reference (round sensibly, write rates as percentages); never invent data; say "
            "'cannot determine' when a source is missing. Be concise and specific."
        )

    async def llm_investigate(self) -> tuple[list[Finding], str]:
        budgets = load_config("budgets")["detective"]
        tools = {t.name: t for t in self.tools()}
        case = self.ctx.case
        brief = (
            f"Case: {case.question} Window {case.window_start:%a %b %d %H:%M} → {case.window_end:%a %b %d %H:%M} "
            f"UTC, compared with {case.baseline_start:%a %b %d} → {case.baseline_end:%a %b %d}.\n"
            "The standard checks already ran. Their computed findings:\n"
            + "\n".join(f"* {f.claim}" for f in self.findings)
            + "\n\n"
            + self.catalogue()
            + "\n\nIf something important is unexplained, call tools to look further; otherwise reply DONE."
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": brief},
        ]
        for step in range(int(budgets.get("max_steps", 8))):
            if not tools:
                break
            r = await self.ctx.llm.chat(
                "nano",
                messages,
                tools=[t.schema() for t in tools.values()],
                tool_choice="auto",
                reasoning=False,
                meter=self.ctx.meter,
                tag=f"{self.name}:loop",
            )
            if not r.tool_calls:
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": r.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id or f"call_{step}_{i}",
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": tc.raw_arguments or json.dumps(tc.arguments),
                            },
                        }
                        for i, tc in enumerate(r.tool_calls)
                    ],
                }
            )
            for i, tc in enumerate(r.tool_calls):
                await self.emit("tool_call", tool=tc.name, args=tc.arguments, by="nano")
                tool = tools.get(tc.name)
                try:
                    result = await tool.fn(**tc.arguments) if tool else {"error": f"unknown tool {tc.name}"}
                except NoSource as e:
                    result = {"cannot_determine": str(e)}
                except Exception as e:  # noqa: BLE001 - surface tool errors to the model
                    result = {"error": f"{type(e).__name__}: {e}"[:300]}
                await self.emit("tool_result", tool=tc.name, result=_short(result))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id or f"call_{step}_{i}",
                        "content": json.dumps(result, default=str)[:6000],
                    }
                )
        return await self.llm_report()

    async def llm_report(self) -> tuple[list[Finding], str]:
        schema = (
            '{"summary": "...", "findings": [{"claim": "...", "kind": "observed|inference", '
            '"evidence_ids": ["ev_..."], "metrics_refs": ["m_..."], "confidence": 0.0-1.0}]}'
        )
        prompt = (
            f"Write your final report as JSON exactly in this shape: {schema}\n"
            "Use only evidence ids and metric ids from the catalogue. Prefer 2-5 strong findings over many weak "
            "ones. 'observed' = directly measured; 'inference' = your interpretation.\n\n"
            "Computed findings so far:\n"
            + "\n".join(
                f"* {f.claim} [evidence {', '.join(f.evidence_ids)}; metrics {', '.join(f.metrics_refs)}]"
                for f in self.findings
            )
            + "\n\n"
            + self.catalogue()
        )
        r = await self.ctx.llm.chat(
            "super",
            [{"role": "system", "content": self.system_prompt()}, {"role": "user", "content": prompt}],
            reasoning=True,
            json_mode=True,
            meter=self.ctx.meter,
            tag=f"{self.name}:report",
        )
        data = r.json()
        out = []
        for f in data.get("findings", []):
            out.append(
                Finding(
                    detective=self.name,
                    claim=str(f.get("claim", ""))[:600],
                    kind="inference" if f.get("kind") == "inference" else "observed",
                    evidence_ids=list(f.get("evidence_ids") or []),
                    metrics_refs=list(f.get("metrics_refs") or []),
                    confidence=float(f.get("confidence", 0.7) or 0.7),
                )
            )
        if not out:
            raise ValueError("model returned no findings")
        return out, str(data.get("summary") or out[0].claim)[:800]

    async def fix_finding(self, f: Finding) -> Finding | None:
        prompt = (
            f"This finding was rejected by the validator: {f.rejection_reason}\n"
            f"Finding: {f.model_dump_json(include={'claim', 'kind', 'evidence_ids', 'metrics_refs'})}\n"
            "Return a corrected finding as JSON with keys claim, kind, evidence_ids, metrics_refs, confidence. "
            "Use only ids from the catalogue and only numbers from referenced metrics.\n\n" + self.catalogue()
        )
        try:
            r = await self.ctx.llm.chat(
                "super",
                [{"role": "system", "content": self.system_prompt()}, {"role": "user", "content": prompt}],
                reasoning=False,
                json_mode=True,
                meter=self.ctx.meter,
                tag=f"{self.name}:fix",
            )
            d = r.json()
            return Finding(
                detective=self.name,
                claim=str(d["claim"])[:600],
                kind="inference" if d.get("kind") == "inference" else "observed",
                evidence_ids=list(d.get("evidence_ids") or []),
                metrics_refs=list(d.get("metrics_refs") or []),
                confidence=float(d.get("confidence", 0.6) or 0.6),
            )
        except Exception:  # noqa: BLE001
            return None


def _short(result: Any, limit: int = 600) -> Any:
    s = json.dumps(result, default=str)
    return result if len(s) <= limit else {"preview": s[:limit] + "…"}
