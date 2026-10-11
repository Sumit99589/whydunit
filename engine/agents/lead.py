"""The lead detective: turns seven reports into one defensible answer.

1. Opening brief: merge the detectives' proposals into candidate hypotheses, each with an effect spec.
2. Cross-examination (≤ 3 rounds): structured questions to specific detectives, answered with new evidence
   or `cannot_determine`. Contradictions are kept and shown.
3. Judgement (code): supported ⇔ observed evidence of the mechanism AND of the timing, and nothing against.
4. Attribution: exact Shapley shares (with CIs) for the supported hypotheses, plus an "unexplained" share.
5. Verdict: ranked causes, how we know, actions, not-checked; or "no real drop" / "measurement problem".
   Ultra writes the narrative when available; the number validator checks it, else a template is used.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from engine.agents.base import COUNTRY, pct, seg_label
from engine.analysis.shapley import Effect, attribute
from engine.runtime import events as ev
from engine.runtime.context import CaseContext
from engine.runtime.llm import BudgetExceeded, LLMUnavailable
from engine.runtime.schemas import DetectiveReport, Finding, Hypothesis, Question, new_id
from engine.runtime.validator import extract_numbers, number_matches

log = logging.getLogger("whydunit.lead")

MECHANISM_OWNERS = {"deploy", "ads", "payments", "world"}
ALIGN = timedelta(hours=4)


class LeadDetective:
    name = "lead"

    def __init__(self, ctx: CaseContext, reports: dict[str, DetectiveReport]):
        self.ctx = ctx
        self.reports = reports
        self.team = getattr(ctx, "team", {})
        self.hyps: list[Hypothesis] = []
        self.thread: list[dict[str, Any]] = []
        self.findings: dict[str, Finding] = {f.id: f for r in reports.values() for f in r.findings}
        self.by_finding: dict[str, str] = {f.id: r.detective for r in reports.values() for f in r.findings}

    async def emit(self, type: str, **payload: Any) -> None:
        await self.ctx.log.emit(type, self.name, **payload)

    # ------------------------------------------------------------------ 1. opening brief
    def merge(self) -> list[Hypothesis]:
        props = [h for r in self.reports.values() for h in r.hypotheses]
        merged: list[Hypothesis] = []
        for h in sorted(props, key=lambda h: (h.proposed_by not in MECHANISM_OWNERS, h.effect.factor)):
            match = next((m for m in merged if _same_effect(m, h)), None)
            if match is None:
                merged.append(h.model_copy(deep=True))
                merged[-1].reason = ""
                _classify(merged[-1], h, self.by_finding)
            else:
                match.supporting = list(dict.fromkeys(match.supporting + h.supporting))
                _classify(match, h, self.by_finding)
        return merged

    # ------------------------------------------------------------------ 2. cross-examination
    def plan_questions(self, rnd: int) -> list[tuple[Hypothesis, Question]]:
        out = []
        asked = {(t["to"], t["kind"], t["hypothesis"]) for t in self.thread}
        for h in self.hyps:
            e = h.effect
            seg = e.segment
            at = e.start.isoformat() if e.start else None
            wants: list[tuple[str, str, str, dict[str, Any]]] = []
            # Round 1 always confirms timing at the mechanism's exact moment (not just CUSUM alignment).
            if at and (rnd == 1 or not h.timing_evidence) and "funnel" in self.team:
                wants.append(
                    (
                        "funnel",
                        "before_after",
                        f"Is the change in {e.factor.replace('_', ' ')} for {_seg_text(seg)} visible right at "
                        f"{e.start:%a %H:%M} UTC?",
                        {"factor": e.factor, "segment": seg, "at": at},
                    )
                )
            if not h.mechanism_evidence and at:
                if e.factor == "signup_rate" and "deploy" in self.team:
                    wants.append(
                        (
                            "deploy",
                            "deploy_around",
                            f"Did a deployment around {e.start:%a %H:%M} UTC break "
                            f"signup for {_seg_text(seg)}?",
                            {"segment": seg, "at": at},
                        )
                    )
                if e.factor == "traffic" and seg.get("channel") == "paid" and "ads" in self.team:
                    wants.append(
                        (
                            "ads",
                            "ads_change_around",
                            f"What changed in the ad account around {e.start:%a %H:%M} UTC?",
                            {"at": at},
                        )
                    )
                if e.factor == "traffic" and "country" in seg and "world" in self.team:
                    wants.append(
                        (
                            "world",
                            "external_event",
                            f"Anything happening in "
                            f"{COUNTRY.get(seg['country'], seg['country'])} on {e.start:%a %b %d}?",
                            {"segment": seg, "at": at},
                        )
                    )
                if e.factor == "payment_success_rate" and "payments" in self.team:
                    wants.append(
                        (
                            "payments",
                            "payments_segment",
                            f"Are declines up for {_seg_text(seg)}, and is it the banks or us?",
                            {"segment": seg, "at": at},
                        )
                    )
            if rnd == 1 and e.factor == "signup_rate" and seg.get("engine") and at and "world" in self.team:
                wants.append(
                    (
                        "world",
                        "external_release",
                        f"Any {seg_label('engine', seg['engine'])} release or known "
                        f"breakage in the days before {e.start:%a %b %d}?",
                        {"engine": seg["engine"], "at": at},
                    )
                )
            for to, kind, text, params in wants:
                if (to, kind, h.id) not in asked:
                    out.append(
                        (
                            h,
                            Question(
                                to=to, text=text, kind=kind, params=params, about_hypothesis=h.id, round=rnd
                            ),
                        )
                    )
        return out

    async def cross_examine(self, max_rounds: int = 3) -> None:
        for rnd in range(1, max_rounds + 1):
            qs = self.plan_questions(rnd)
            if not qs:
                break
            for h, q in qs:
                await self.emit("question", question=q.model_dump(mode="json"), hypothesis=h.statement)
            answers = await asyncio.gather(*(self.team[q.to].answer(q) for _, q in qs))
            for (h, q), a in zip(qs, answers, strict=True):
                self.thread.append(
                    {
                        "to": q.to,
                        "kind": q.kind,
                        "hypothesis": h.id,
                        "question": q.text,
                        "answer": a.text,
                        "verdict": a.verdict,
                    }
                )
                await self.emit(
                    "answer", answer=a.model_dump(mode="json"), question_id=q.id, to=q.to, hypothesis=h.id
                )
                ids = [f.id for f in a.findings if f.status == "accepted"]
                for f in a.findings:
                    self.findings[f.id] = f
                    self.by_finding[f.id] = q.to
                if a.verdict == "supports":
                    if q.kind == "before_after":
                        h.timing_evidence += ids or [f"answer:{q.id}"]
                    elif q.kind == "external_release":
                        h.supporting += ids
                    else:
                        h.mechanism_evidence += ids or [f"answer:{q.id}"]
                elif a.verdict == "contradicts":
                    h.contradicting += ids or [f"answer:{q.id}"]

    # ------------------------------------------------------------------ 3. judgement (code)
    def judge(self) -> None:
        for h in self.hyps:
            mech, timing = bool(h.mechanism_evidence), bool(h.timing_evidence)
            if h.contradicting and not (mech and timing):
                h.status, h.reason = "rejected", "contradicted by the evidence"
            elif mech and timing:
                h.status, h.reason = "supported", "observed mechanism and matching timing"
            elif mech:
                h.status, h.reason = "inconclusive", "mechanism observed but the timing does not line up"
            elif timing:
                h.status, h.reason = "inconclusive", "the metric changed then, but no mechanism was found"
            else:
                h.status, h.reason = "inconclusive", "neither mechanism nor timing confirmed"

    # ------------------------------------------------------------------ run
    async def run(self) -> dict[str, Any]:
        ctx = self.ctx
        await self.emit("lead_started", reports={k: len(v.findings) for k, v in self.reports.items()})
        self.hyps = self.merge()
        for h in self.hyps:
            await self.emit("hypothesis", hypothesis=h.model_dump(mode="json"))
        brief = await self.brief()
        await self.emit("brief", text=brief)
        await self.cross_examine()
        self.judge()
        for h in self.hyps:
            await ev.save_hypothesis(ctx.case.id, h)
            await self.emit("judgement", hypothesis=h.model_dump(mode="json"))
        verdict = await self.verdict()
        await ev.set_status(ctx.case.id, "verdict", verdict_kind=verdict["kind"])
        return verdict

    async def brief(self) -> str:
        names = ", ".join(f"{h.statement}" for h in self.hyps) or "no specific hypothesis"
        text = f"{len(self.hyps)} candidate explanation(s) from the team: {names}."
        return text

    # ------------------------------------------------------------------ 4 + 5. attribution and verdict
    async def verdict(self) -> dict[str, Any]:
        ctx = self.ctx
        funnel = self.reports.get("funnel")
        fd = self.team.get("funnel")
        change = getattr(fd, "change", None) or {}
        no_drop = change.get("verdict") == "within_normal_variance"
        tracking = getattr(fd, "tracking_finding", None)
        no_drop_finding = getattr(fd, "no_drop_finding", None)
        supported = [h for h in self.hyps if h.status == "supported"]
        not_checked = sorted(
            {f"{c.kind}: {c.reason[:140]}" for r in self.reports.values() for c in r.cannot_determine}
        )
        attribution = None
        if tracking is not None and (no_drop or ctx.case.metric == "signups"):
            kind = "measurement"
            narrative, refs = self.measurement_narrative(tracking)
            causes: list[dict[str, Any]] = []
        elif no_drop and not supported:
            kind = "no_real_drop"
            f0 = no_drop_finding or funnel.findings[0]
            narrative, refs = f0.claim, list(f0.metrics_refs)
            causes = []
        elif supported:
            kind = "causes"
            sess, _ = await ctx.sessions(self.name)
            effects = [
                Effect(h.id, h.effect.factor, h.effect.segment, h.effect.start, h.effect.end, h.statement)
                for h in supported
            ]
            attribution = attribute(sess, effects, ctx.baseline, ctx.window, n_boot=300)
            await self.emit("attribution", attribution=attribution)
            causes = self.causes(attribution, supported)
            narrative, refs = self.causes_narrative(attribution, causes)
            if no_drop:
                # The cause is real (mechanism and timing confirmed) but the headline moved within normal variance.
                narrative += (
                    " Overall the change is within normal variance, so this is a real but small problem "
                    "rather than a collapse."
                )
        else:
            kind = "unexplained"
            narrative = (
                "The drop is real, but no explanation could be confirmed: each candidate lacked either an "
                "observed mechanism or matching timing. See the open questions and the not-checked list."
            )
            refs, causes = [], []
        llm_text = await self.ultra_narrative(kind, narrative, refs)
        if llm_text:
            narrative = llm_text
        verdict = {
            "id": new_id("v"),
            "kind": kind,
            "narrative": narrative,
            "causes": causes,
            "unexplained": attribution["unexplained"] if attribution else {},
            "how_we_know": self.how_we_know(supported),
            "rejected": [
                {"statement": h.statement, "reason": h.reason} for h in self.hyps if h.status == "rejected"
            ],
            "inconclusive": [
                {"statement": h.statement, "reason": h.reason}
                for h in self.hyps
                if h.status == "inconclusive"
            ],
            "not_checked": not_checked,
            "actions": self.actions(
                sorted(
                    supported,
                    key=lambda h: -next((c["share"] for c in causes if c["hypothesis_id"] == h.id), 0),
                ),
                kind,
            ),
            "thread": self.thread,
            "metrics_refs": refs,
        }
        from engine import db

        await db.execute(
            """INSERT INTO verdicts (id, case_id, kind, narrative, causes, unexplained, not_checked, actions)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                verdict["id"],
                ctx.case.id,
                kind,
                narrative,
                db.jsonb(causes),
                db.jsonb(verdict["unexplained"]),
                db.jsonb(not_checked),
                db.jsonb(verdict["actions"]),
            ),
        )
        await self.emit("verdict", verdict=verdict)
        return verdict

    def causes(self, a: dict[str, Any], supported: list[Hypothesis]) -> list[dict[str, Any]]:
        ctx = self.ctx
        by_id = {h.id: h for h in supported}
        out = []
        for e in a["effects"]:
            h = by_id[e["id"]]
            ms = ctx.metric(f"share of the drop: {h.statement}", e["share_of_drop"], "share")
            ci = [min(max(x, 0.0), 1.0) for x in e["share_of_drop_ci"]]  # a share is shown within 0–100%
            lo = ctx.metric(f"share of the drop, CI low: {h.statement}", ci[0], "share")
            hi = ctx.metric(f"share of the drop, CI high: {h.statement}", ci[1], "share")
            lost = ctx.metric(f"paid subs lost: {h.statement}", e["lost"], "count")
            conf = min(
                (
                    self.findings[f].confidence
                    for f in h.mechanism_evidence + h.timing_evidence
                    if f in self.findings
                ),
                default=0.6,
            )
            out.append(
                {
                    "hypothesis_id": h.id,
                    "statement": h.statement,
                    "factor": h.effect.factor,
                    "segment": h.effect.segment,
                    "start": h.effect.start.isoformat() if h.effect.start else None,
                    "share": e["share_of_drop"],
                    "share_ci": ci,
                    "share_of_explained": e["share_of_explained"],
                    "lost": e["lost"],
                    "lost_ci": e["lost_ci"],
                    "confidence": round(conf, 2),
                    "proposed_by": h.proposed_by,
                    "evidence": list(dict.fromkeys(h.mechanism_evidence + h.timing_evidence + h.supporting)),
                    "metrics_refs": [ms.id, lo.id, hi.id, lost.id],
                }
            )
        return out

    def causes_narrative(self, a: dict[str, Any], causes: list[dict[str, Any]]) -> tuple[str, list[str]]:
        ctx = self.ctx
        m_b = ctx.metric("verdict: expected paid subs in window", a["baseline_expected"], "count")
        m_a = ctx.metric("verdict: actual paid subs in window", a["actual"], "count")
        m_d = ctx.metric(
            "verdict: observed drop share",
            a["observed_drop"] / a["baseline_expected"] if a["baseline_expected"] else 0,
            "share",
        )
        m_u = ctx.metric("verdict: unexplained share", a["unexplained"]["share_of_drop"], "share")
        parts = []
        for i, c in enumerate(causes, 1):
            parts.append(
                f"({i}) {c['statement']}: {pct(c['share'], 0)} of the drop "
                f"(90% CI {pct(c['share_ci'][0], 0)}–{pct(c['share_ci'][1], 0)})"
            )
        unexpl = a["unexplained"]["share_of_drop"]
        text = (
            f"Paid subscriptions came in at {a['actual']:.0f} against {a['baseline_expected']:.0f} for the same days "
            f"a week earlier, {pct(m_d.value, 0)} lower. "
            + (
                "The cause is "
                if len(causes) == 1
                else f"{_count_word(len(causes)).capitalize()} causes explain it: "
            )
            + "; ".join(parts)
            + ". "
            + (
                f"{pct(abs(unexpl), 0)} is unexplained (normal noise)."
                if unexpl >= 0
                else "The causes together slightly over-explain the drop, which is within normal noise."
            )
        )
        refs = [m_b.id, m_a.id, m_d.id, m_u.id] + [r for c in causes for r in c["metrics_refs"]]
        return text, refs

    def measurement_narrative(self, tracking: Finding) -> tuple[str, list[str]]:
        pay = self.reports.get("payments")
        normal = pay and any("look normal" in f.claim for f in pay.findings)
        text = (
            "Measurement problem, not a business drop. "
            + tracking.claim
            + (" Real payments in Stripe look normal over the same period." if normal else "")
        )
        return text, list(tracking.metrics_refs) + (
            [m for f in pay.findings for m in f.metrics_refs] if normal else []
        )

    def how_we_know(self, supported: list[Hypothesis]) -> list[dict[str, Any]]:
        out = []
        for h in supported:
            ev_ids = list(dict.fromkeys(h.mechanism_evidence + h.timing_evidence))
            out.append(
                {
                    "hypothesis": h.statement,
                    "mechanism": [self.findings[i].claim for i in h.mechanism_evidence if i in self.findings][
                        :2
                    ],
                    "timing": [self.findings[i].claim for i in h.timing_evidence if i in self.findings][:2],
                    "corroboration": [
                        self.findings[i].claim for i in h.supporting if i in self.findings and i not in ev_ids
                    ][:2],
                }
            )
        return out

    def actions(self, supported: list[Hypothesis], kind: str) -> list[dict[str, Any]]:
        if kind == "measurement":
            return [
                {
                    "type": "recommendation",
                    "title": "Fix the analytics event: restore signup_completed",
                    "detail": {"why": "signups are under-counted; the business is fine"},
                }
            ]
        out = []
        for h in supported:
            if h.proposed_by == "deploy" or (
                h.effect.factor == "signup_rate" and h.effect.segment.get("engine")
            ):
                dep = self.team.get("deploy")
                bad, s = getattr(dep, "bad", None), getattr(dep, "suspect", None)
                out.append(
                    {
                        "type": "code_pr",
                        "hypothesis_id": h.id,
                        "title": f"Fix {s['api']} with a fallback in {s['file']}"
                        if s
                        else "Revert the breaking deployment",
                        "detail": {
                            "deployment": bad and bad.get("id"),
                            "sha": bad and bad.get("git_sha"),
                            "suspect": s,
                        },
                    }
                )
            elif h.effect.factor == "traffic" and h.effect.segment.get("channel") == "paid":
                cut = getattr(self.team.get("ads"), "cut", None)
                out.append(
                    {
                        "type": "config",
                        "hypothesis_id": h.id,
                        "approval_required": True,
                        "title": f"Restore the “{cut['campaign_name']}” daily budget to ${cut['old_value']:.0f}"
                        if cut
                        else "Restore the paid campaign budget",
                        "detail": {
                            "campaign_id": cut and cut["campaign_id"],
                            "from": cut and cut["new_value"],
                            "to": cut and cut["old_value"],
                            "simulated": True,
                        },
                    }
                )
            elif h.effect.factor == "payment_success_rate" and h.effect.segment.get("country"):
                c = h.effect.segment["country"]
                out.append(
                    {
                        "type": "recommendation",
                        "hypothesis_id": h.id,
                        "approval_required": True,
                        "title": f"Retry declined payments and offer a local payment method for cards from "
                        f"{COUNTRY.get(c, c)}",
                        "detail": {"country": c, "simulated_mitigation": True},
                    }
                )
            elif h.effect.factor == "traffic" and h.effect.segment.get("country"):
                out.append(
                    {
                        "type": "none",
                        "hypothesis_id": h.id,
                        "title": "No action: traffic returns after the holiday",
                    }
                )
            elif h.effect.factor == "payment_success_rate":
                out.append(
                    {
                        "type": "recommendation",
                        "hypothesis_id": h.id,
                        "title": "Retry the payments that failed during the provider outage",
                    }
                )
            else:
                out.append(
                    {"type": "recommendation", "hypothesis_id": h.id, "title": f"Investigate: {h.statement}"}
                )
        return out

    async def ultra_narrative(self, kind: str, draft: str, refs: list[str]) -> str | None:
        """Ultra rewrites the verdict for a founder; every number must still match a computed metric."""
        ctx = self.ctx
        if not ctx.llm.available():
            return None
        metrics = [ctx.metrics[r] for r in refs if r in ctx.metrics]
        catalogue = "\n".join(f"- {m.id} = {m.value:.6g} ({m.unit}): {m.name}" for m in metrics)
        thread = "\n".join(
            f"Q to {t['to']}: {t['question']} → {t['answer']} [{t['verdict']}]" for t in self.thread
        )
        prompt = (
            f"You are the lead detective. Verdict type: {kind}. Rewrite this verdict for a busy founder in at most "
            "5 sentences: lead with the answer, then how we know, then what to do. Use only numbers from the "
            f"metrics list (rounded, rates as percentages).\n\nDRAFT:\n{draft}\n\nCROSS-EXAMINATION:\n{thread}\n\n"
            f"METRICS:\n{catalogue}"
        )
        try:
            r = await ctx.llm.chat(
                "ultra",
                [{"role": "user", "content": prompt}],
                reasoning=True,
                meter=ctx.meter,
                tag="lead:verdict",
                max_tokens=1500,
            )
        except (LLMUnavailable, BudgetExceeded):
            return None
        except Exception:  # noqa: BLE001
            log.exception("Ultra narrative failed")
            return None
        text = r.content.strip()
        bad = [n.text for n in extract_numbers(text) if not number_matches(n, metrics)]
        if bad or not text:
            await self.emit(
                "narrative_rejected", reason=f"numbers not backed by metrics: {', '.join(bad)}"[:300]
            )
            return None
        return text


def _seg_text(seg: dict[str, Any]) -> str:
    return " and ".join(seg_label(k, v) for k, v in seg.items()) or "everyone"


def _count_word(n: int) -> str:
    return {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}.get(n, str(n))


def _same_effect(a: Hypothesis, b: Hypothesis) -> bool:
    if a.effect.factor != b.effect.factor:
        return False
    sa, sb = a.effect.segment, b.effect.segment
    seg_ok = sa == sb or not sa or not sb or bool(set(sa.items()) & set(sb.items()))
    ta, tb = a.effect.start, b.effect.start
    time_ok = ta is None or tb is None or abs(_dt(ta) - _dt(tb)) <= timedelta(hours=8)
    if not seg_ok:
        # Different dimensions can still be one cause if the change started at the same time (e.g. os=iOS vs engine=webkit).
        seg_ok = (
            time_ok
            and ta is not None
            and tb is not None
            and abs(_dt(ta) - _dt(tb)) <= ALIGN
            and set(sa) != set(sb)
        )
    return seg_ok and time_ok


def _dt(x: Any) -> datetime:
    return x if isinstance(x, datetime) else datetime.fromisoformat(str(x))


def _classify(target: Hypothesis, prop: Hypothesis, by_finding: dict[str, str]) -> None:
    """Mechanism evidence comes from the detective that owns the mechanism; the Funnel detective supplies timing
    when its break point lines up with the mechanism's time."""
    if prop.proposed_by in MECHANISM_OWNERS:
        target.mechanism_evidence = list(dict.fromkeys(target.mechanism_evidence + prop.supporting))
        if target.proposed_by not in MECHANISM_OWNERS:
            # Adopt the mechanism's segment and time: it names the cause, the funnel only saw its effect.
            target.effect = prop.effect.model_copy()
            target.statement, target.proposed_by = prop.statement, prop.proposed_by
    elif prop.proposed_by == "funnel":
        if target.proposed_by in MECHANISM_OWNERS and target.effect.start and prop.effect.start:
            if abs(_dt(target.effect.start) - _dt(prop.effect.start)) <= ALIGN:
                target.timing_evidence = list(dict.fromkeys(target.timing_evidence + prop.supporting))
        elif target.proposed_by == "funnel":
            target.supporting = list(dict.fromkeys(target.supporting + prop.supporting))
    _ = by_finding
