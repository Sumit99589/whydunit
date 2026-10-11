"""The Funnel detective: where in the funnel did the drop happen, in which segment, and since when?"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import polars as pl

from engine.agents.base import Detective, Tool, pct, seg_label
from engine.analysis.changepoint import assess_change, cusum
from engine.analysis.data import DIMS, FACTORS
from engine.analysis.decompose import decompose
from engine.analysis.segments import drilldown, factor_by_segment

FACTOR_LABEL = {
    "traffic": "Visitors",
    "signup_rate": "Signup rate",
    "checkout_rate": "Checkout rate",
    "payment_success_rate": "Payment success rate",
}
MIN_SHARE = 0.08  # a factor must explain at least this share of the change to be reported
DIM_PREFERENCE = {"engine": 0, "channel": 1, "country": 2, "device": 3, "os": 4, "browser": 5}


class FunnelDetective(Detective):
    def __init__(self, ctx):
        super().__init__(
            ctx,
            name="funnel",
            title="Funnel detective",
            mission="You own the conversion funnel: traffic × signup rate × checkout rate × payment "
            "success rate, broken down by segment and over time.",
        )
        self.sess: pl.DataFrame | None = None
        self.events_id = ""

    async def playbook(self) -> None:
        ctx = self.ctx
        sess, events = await ctx.sessions(self.name)
        self.sess, self.events_id = sess, events.id
        await self.emit("tool_call", tool="assess_change", args={"metric": "paid_subs"}, by="playbook")
        ch = assess_change(sess, "paid", ctx.window, ctx.baseline, ctx.history_start)
        d = decompose(sess, ctx.baseline, ctx.window)
        dec_ev = await self.analysis(
            "funnel_decomposition",
            [{k: v for k, v in f.items() if k != "log_ratio"} for f in d["factors"]],
            f"Funnel decomposition: paid subs {d['baseline_per_day']:.1f}/day → {d['window_per_day']:.1f}/day",
            [events.id],
            ctx.case_window,
        )
        chg_ev = await self.analysis(
            "change_assessment",
            ch["daily"],
            f"Paid subs vs {ch['expectation']}: {ch['observed']:.0f} observed vs {ch['expected']:.0f} expected "
            f"(z = {ch['z']:.1f}) — {ch['verdict'].replace('_', ' ')}",
            [events.id],
            ctx.full_window,
        )
        m_b = ctx.metric("paid subs per day, baseline", d["baseline_per_day"], "per_day", [dec_ev.id])
        m_w = ctx.metric("paid subs per day, window", d["window_per_day"], "per_day", [dec_ev.id])
        m_pc = ctx.metric("paid subs change vs baseline", d["pct_change"] or 0.0, "pct_change", [dec_ev.id])
        m_exp = ctx.metric("paid subs expected in window (seasonal)", ch["expected"], "count", [chg_ev.id])
        m_obs = ctx.metric("paid subs observed in window", ch["observed"], "count", [chg_ev.id])
        ctx.metric(  # registered for the model to cite
            "paid subs change vs seasonal expectation", ch["relative_change"], "pct_change", [chg_ev.id]
        )
        m_z = ctx.metric("paid subs z-score vs normal variance", ch["z"], "z", [chg_ev.id])
        self.change = ch
        await self.emit(
            "tool_result", tool="assess_change", result={"verdict": ch["verdict"], "z": round(ch["z"], 2)}
        )

        if ch["verdict"] == "within_normal_variance":
            naive = ch["naive_relative_change_vs_baseline"]
            refs = [m_obs.id, m_exp.id, m_z.id]
            extra = ""
            if naive is not None and naive < -0.05:
                m_naive = ctx.metric(
                    "paid subs change vs case baseline (naive)", naive, "pct_change", [chg_ev.id]
                )
                refs.append(m_naive.id)
                extra = (
                    f" Against the case baseline it looks like a {pct(abs(naive), 0)} drop, but the same days in "
                    "previous weeks look the same: this is the usual pattern, not a new problem."
                )
            self.add_finding(
                f"No real drop: {ch['observed']:.0f} paid subscriptions in the window against {ch['expected']:.0f} "
                f"expected from the same weekdays in prior weeks (z = {ch['z']:.1f}), within normal variance.{extra}",
                [events.id, chg_ev.id],
                refs,
                confidence=0.9,
            )
            return

        self.add_finding(
            f"Paid subscriptions fell from {d['baseline_per_day']:.1f} to {d['window_per_day']:.1f} per day "
            f"({pct(abs(d['pct_change']), 0)} lower); {ch['observed']:.0f} in the window against {ch['expected']:.0f} "
            f"expected for those weekdays (z = {ch['z']:.1f}), so this is a real drop, not noise.",
            [events.id, dec_ev.id, chg_ev.id],
            [m_b.id, m_w.id, m_pc.id, m_obs.id, m_exp.id, m_z.id],
            confidence=0.95,
        )

        total = d["change_per_day"]
        for f in sorted(d["factors"], key=lambda f: f["contribution_per_day"]):
            share = f["contribution_per_day"] / total if total else 0
            if f["contribution_per_day"] >= 0 or share < MIN_SHARE:
                continue
            await self.explain_factor(f, share, dec_ev.id)
        await self.integrity_check(sess, events.id)

    async def explain_factor(self, f: dict[str, Any], share: float, dec_id: str) -> None:
        ctx, sess = self.ctx, self.sess
        assert sess is not None
        factor = f["factor"]
        await self.emit("tool_call", tool="segment_drilldown", args={"factor": factor}, by="playbook")
        top = drilldown(sess, factor, ctx.baseline, ctx.window, top=6)
        if not top:
            return
        # The segment that explains the most; on near-ties prefer the more causal dimension (engine > os...).
        best = top[0]["contribution"]
        cands = [t for t in top if t["contribution"] <= best * 0.9] or top[:1]
        seg = sorted(cands, key=lambda t: (DIM_PREFERENCE.get(t["dim"], 9), t["contribution"]))[0]
        await self.emit(
            "tool_result",
            tool="segment_drilldown",
            result={
                "top": [
                    {"dim": t["dim"], "value": t["value"], "share": round(t["share_of_factor_change"], 3)}
                    for t in top[:4]
                ]
            },
        )
        seg_rows = factor_by_segment(sess, factor, seg["dim"], ctx.baseline, ctx.window)
        seg_ev = await self.analysis(
            f"segments_{factor}_{seg['dim']}",
            [{k: v for k, v in r.items()} for r in seg_rows],
            f"{FACTOR_LABEL[factor]} by {seg['dim']}: {seg_label(seg['dim'], seg['value'])} explains "
            f"{pct(seg['share_of_factor_change'], 0)} of the change",
            [self.events_id],
            ctx.case_window,
            factor=factor,
            dim=seg["dim"],
        )
        segment = {seg["dim"]: seg["value"]}
        await self.emit(
            "tool_call", tool="change_timing", args={"factor": factor, "segment": segment}, by="playbook"
        )
        timing = cusum(sess, factor, ctx.baseline, ctx.window, segment)
        await self.emit("tool_result", tool="change_timing", result=timing)
        t_ev = await self.analysis(
            f"timing_{factor}_{seg['dim']}_{seg['value']}",
            [timing],
            f"{FACTOR_LABEL[factor]} for {seg_label(seg['dim'], seg['value'])}: "
            + (
                f"broke from baseline around {timing['changed_at'][:16].replace('T', ' ')} UTC"
                if timing["detected"]
                else "no clear break point"
            ),
            [self.events_id],
            ctx.case_window,
            factor=factor,
            segment=segment,
        )

        m_share = ctx.metric(f"{factor} share of paid subs change", share, "share", [dec_id])
        label, sl = FACTOR_LABEL[factor], seg_label(seg["dim"], seg["value"])
        m_seg_share = ctx.metric(
            f"{sl} share of {factor} change", seg["share_of_factor_change"], "share", [seg_ev.id]
        )
        when = ""
        if timing["detected"]:
            when = f", starting around {datetime.fromisoformat(timing['changed_at']):%a %b %d %H:%M} UTC"
        if factor == "traffic":
            m0 = ctx.metric(f"visitors per day, {sl}, baseline", seg["baseline"], "per_day", [seg_ev.id])
            m1 = ctx.metric(f"visitors per day, {sl}, window", seg["window"], "per_day", [seg_ev.id])
            how_much = (
                "essentially all"
                if seg["share_of_factor_change"] >= 0.95
                else pct(seg["share_of_factor_change"], 0)
            )
            claim = (
                f"Traffic fell and accounts for {pct(share, 0)} of the drop. {sl[0].upper() + sl[1:]} explains "
                f"{how_much} of the lost visitors: {seg['baseline']:.0f} → {seg['window']:.0f} per day{when}."
            )
        else:
            r0, r1 = seg["baseline"] or 0.0, seg["window"] or 0.0
            m0 = ctx.metric(f"{factor}, {sl}, baseline", r0, "rate", [seg_ev.id])
            m1 = ctx.metric(f"{factor}, {sl}, window", r1, "rate", [seg_ev.id])
            how_much = (
                "essentially all"
                if seg["share_of_factor_change"] >= 0.95
                else pct(seg["share_of_factor_change"], 0)
            )
            claim = (
                f"{label} fell and accounts for {pct(share, 0)} of the drop. It is concentrated in {sl} "
                f"({how_much} of the fall): {pct(r0)} → {pct(r1)}{when}."
            )
        refs = [m_share.id, m_seg_share.id, m0.id, m1.id]
        within = seg.get("within") or []
        if within and factor != "traffic":
            sub = within[0]
            parts = [p for p in sub["parts"] if p["baseline"] is not None and p["window"] is not None][:3]
            if parts and all((p["window"] or 0) < (p["baseline"] or 1) * 0.5 for p in parts):
                claim += f" It happens on every {sub['dim']} within that segment, so the {sub['dim']} is not the cause."
        self.add_finding(claim, [self.events_id, dec_id, seg_ev.id, t_ev.id], refs, confidence=0.9)
        start = timing.get("changed_at") if timing["detected"] else None
        verb = {
            "traffic": "fewer visitors",
            "signup_rate": "visitors cannot or do not sign up",
            "checkout_rate": "fewer signups reach checkout",
            "payment_success_rate": "payments fail more often",
        }[factor]
        self.propose(
            f"Something changed for {sl}: {verb}"
            + (f" since {start[:16].replace('T', ' ')} UTC" if start else ""),
            factor,
            segment,
            start,
            [],
        )

    async def integrity_check(self, sess: pl.DataFrame, events_id: str) -> None:
        """Downstream events without upstream ones mean the tracking broke, not the business."""
        ctx = self.ctx

        def gap(period):
            s = period.filter(sess).filter(pl.col("raw_checkout_started") | pl.col("raw_payment_succeeded"))
            return (s.filter(~pl.col("raw_signup_completed")).height / s.height) if s.height else 0.0

        g0, g1 = gap(ctx.baseline), gap(ctx.window)
        if g1 - g0 > 0.2:
            ev = await self.analysis(
                "tracking_integrity",
                [{"baseline_gap": g0, "window_gap": g1}],
                "Sessions that reached checkout without a signup_completed event",
                [events_id],
                ctx.case_window,
            )
            m0 = ctx.metric("checkout sessions missing signup_completed, baseline", g0, "share", [ev.id])
            m1 = ctx.metric("checkout sessions missing signup_completed, window", g1, "share", [ev.id])
            self.add_finding(
                f"Tracking looks broken: {pct(g1, 0)} of sessions that reached checkout have no signup_completed event "
                f"(baseline {pct(g0, 0)}). Signups are being under-counted; this may be a measurement problem.",
                [events_id, ev.id],
                [m0.id, m1.id],
                kind="inference",
                confidence=0.85,
            )

    def template_summary(self) -> str:
        return " ".join(f.claim.split(". ")[0] + "." for f in self.findings[:3]) or "No funnel data."

    def tools(self) -> list[Tool]:
        ctx = self.ctx

        async def segment_breakdown(
            factor: str, dim: str, within_dim: str | None = None, within_value: str | None = None
        ):
            assert self.sess is not None
            within = {within_dim: within_value} if within_dim and within_value else None
            rows = factor_by_segment(self.sess, factor, dim, ctx.baseline, ctx.window, within)
            ev = await self.analysis(
                f"segments_{factor}_{dim}_{within_dim}_{within_value}",
                rows,
                f"{FACTOR_LABEL.get(factor, factor)} by {dim}" + (f" within {within}" if within else ""),
                [self.events_id],
                ctx.case_window,
                factor=factor,
                dim=dim,
                within=within,
            )
            out = []
            for r in rows[:8]:
                m0 = ctx.metric(
                    f"{factor}, {dim}={r['value']}{' in ' + str(within) if within else ''}, baseline",
                    r["baseline"] or 0,
                    "per_day" if factor == "traffic" else "rate",
                    [ev.id],
                )
                m1 = ctx.metric(
                    f"{factor}, {dim}={r['value']}{' in ' + str(within) if within else ''}, window",
                    r["window"] or 0,
                    "per_day" if factor == "traffic" else "rate",
                    [ev.id],
                )
                out.append(
                    {
                        "value": r["value"],
                        "baseline": m0.id,
                        "window": m1.id,
                        "share_of_change": round(r["share_of_factor_change"], 3),
                    }
                )
            return {"evidence_id": ev.id, "segments": out}

        async def change_timing(factor: str, dim: str, value: str):
            assert self.sess is not None
            r = cusum(self.sess, factor, ctx.baseline, ctx.window, {dim: value})
            ev = await self.analysis(
                f"timing_{factor}_{dim}_{value}",
                [r],
                f"Change timing for {factor} in {dim}={value}",
                [self.events_id],
                ctx.case_window,
            )
            return {"evidence_id": ev.id, **r}

        enum_f = {"type": "string", "enum": list(FACTORS)}
        enum_d = {"type": "string", "enum": list(DIMS)}
        return [
            Tool(
                "segment_breakdown",
                "Break a funnel factor's change down by one segment dimension, optionally "
                "inside another segment.",
                {
                    "type": "object",
                    "properties": {
                        "factor": enum_f,
                        "dim": enum_d,
                        "within_dim": enum_d,
                        "within_value": {"type": "string"},
                    },
                    "required": ["factor", "dim"],
                },
                segment_breakdown,
            ),
            Tool(
                "change_timing",
                "Find when a funnel factor broke from its baseline within a segment (CUSUM).",
                {
                    "type": "object",
                    "properties": {"factor": enum_f, "dim": enum_d, "value": {"type": "string"}},
                    "required": ["factor", "dim", "value"],
                },
                change_timing,
            ),
        ]
