"""Case lifecycle: open a case on a world, run detectives concurrently, hand their reports to the lead."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from engine.connectors import Registry, registry_for
from engine.runtime import events as ev
from engine.runtime.context import CaseContext
from engine.runtime.llm import LLM
from engine.runtime.schemas import Case, DetectiveReport

log = logging.getLogger("whydunit.orchestrator")


def detective_classes() -> dict[str, type]:
    from engine.agents.funnel import FunnelDetective

    out: dict[str, type] = {"funnel": FunnelDetective}
    try:
        from engine.agents import team

        out |= team.DETECTIVES
    except ImportError:
        pass
    return out


async def case_window_for(world: str, registry: Registry, window_days: float = 3.0) -> dict[str, datetime]:
    if registry.mode == "fixture":
        fw = registry.connectors[0]
        spec = await fw.case_spec()  # type: ignore[attr-defined]
        out = {
            k: datetime.fromisoformat(spec[k])
            for k in ("window_start", "window_end", "baseline_start", "baseline_end")
        }
        out["history_start"] = datetime.fromisoformat(fw.meta()["start"])  # type: ignore[attr-defined]
        return out
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    w0 = now - timedelta(days=window_days)
    return {
        "window_start": w0,
        "window_end": now,
        "baseline_start": w0 - timedelta(days=7),
        "baseline_end": now - timedelta(days=7),
    }


async def open_case(
    world: str,
    metric: str = "paid_subs",
    *,
    question: str | None = None,
    auto_opened: bool = False,
    window: dict[str, datetime] | None = None,
    registry: Registry | None = None,
) -> tuple[Case, Registry]:
    registry = registry or registry_for(world)
    w = window or await case_window_for(world, registry)
    labels = {"paid_subs": "new paid subscriptions", "signups": "signups", "visitors": "visitors"}
    case = Case(
        world=world,
        metric=metric,
        question=question or f"Why did {labels.get(metric, metric)} fall?",
        auto_opened=auto_opened,
        history_start=w.get("history_start"),
        **{k: v for k, v in w.items() if k != "history_start"},
    )
    await ev.save_case(case)
    log_ = await ev.CaseLog(case.id).init()
    await log_.emit(
        "case_opened",
        "whydunit",
        case=case.model_dump(mode="json"),
        world_label=registry.label,
        world_mode=registry.mode,
    )
    return case, registry


async def run_detectives(
    case: Case, registry: Registry, names: list[str] | None = None, *, llm: LLM | None = None
) -> tuple[CaseContext, dict[str, DetectiveReport]]:
    log_ = await ev.CaseLog(case.id).init()
    ctx = CaseContext(case, registry, log_, llm=llm)
    classes = detective_classes()
    names = names or list(classes)
    team = [classes[n](ctx) for n in names]
    results = await asyncio.gather(*(d.run() for d in team), return_exceptions=True)
    reports: dict[str, DetectiveReport] = {}
    for d, r in zip(team, results, strict=True):
        if isinstance(r, BaseException):
            log.error("detective %s crashed: %s", d.name, r)
            await log_.emit("detective_error", d.name, error=f"{type(r).__name__}: {r}"[:300])
            reports[d.name] = DetectiveReport(detective=d.name, summary=f"Crashed: {type(r).__name__}")
        else:
            reports[d.name] = r
    return ctx, reports


async def investigate(
    world: str,
    metric: str = "paid_subs",
    *,
    detectives: list[str] | None = None,
    llm: LLM | None = None,
    with_lead: bool = True,
    **kw: Any,
) -> dict[str, Any]:
    case, registry = await open_case(world, metric, **kw)
    ctx, reports = await run_detectives(case, registry, detectives, llm=llm)
    verdict = None
    if with_lead:
        try:
            from engine.agents.lead import LeadDetective
        except ImportError:
            LeadDetective = None  # noqa: N806
        if LeadDetective is not None:
            verdict = await LeadDetective(ctx, reports).run()
    await ev.set_status(
        case.id, "verdict" if verdict else "investigating", cost=ctx.meter.summary(), detectives=list(reports)
    )
    await ctx.log.emit(
        "investigation_complete",
        "whydunit",
        cost=ctx.meter.summary(),
        reports={
            k: {
                "findings": len(v.findings),
                "suspicions": len(v.suspicions),
                "cannot_determine": len(v.cannot_determine),
                "mode": v.model_mode,
            }
            for k, v in reports.items()
        },
    )
    return {"case": case, "ctx": ctx, "reports": reports, "verdict": verdict}
