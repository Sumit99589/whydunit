"""The Payments detective: are payments failing more, for whom, and is it the bank or us?"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import polars as pl

from engine.agents.base import Detective, Tool, pct, seg_label
from engine.connectors.base import Window

MIN_N = 15


class PaymentsDetective(Detective):
    def __init__(self, ctx):
        super().__init__(
            ctx,
            name="payments",
            title="Payments detective",
            mission="You own payments: success rate by day, decline codes, card country and brand, and "
            "whether failures come from card issuers or from Acme's own side.",
        )

    async def playbook(self) -> None:
        ctx = self.ctx
        b = await self.fetch("payments", Window(ctx.case.baseline_start, ctx.case.window_end))
        if b is None:
            return
        df = b.frame.with_columns(pl.col("created").dt.convert_time_zone("UTC"))
        base = df.filter(
            (pl.col("created") >= ctx.case.baseline_start) & (pl.col("created") < ctx.case.baseline_end)
        )
        win = df.filter(
            (pl.col("created") >= ctx.case.window_start) & (pl.col("created") < ctx.case.window_end)
        )
        if base.height < MIN_N or win.height < MIN_N:
            self.add_finding(
                "Too few payment attempts in the baseline or window to compare.", [b.id], [], confidence=0.5
            )
            return

        def rates(d: pl.DataFrame) -> dict[str, float]:
            n = d.height
            return {
                "n": n,
                "success": d.filter(pl.col("status") == "succeeded").height / n,
                "issuer": d.filter(pl.col("outcome_type") == "issuer_declined").height / n,
                "ours": d.filter(pl.col("outcome_type").is_in(["api_error", "invalid", "blocked"])).height
                / n,
            }

        r0, r1 = rates(base), rates(win)
        seg_col = "country" if df["country"].null_count() < df.height else "card_country"
        by_seg = []
        for val in sorted(
            set(win[seg_col].drop_nulls().to_list()) | set(base[seg_col].drop_nulls().to_list())
        ):
            s0, s1 = base.filter(pl.col(seg_col) == val), win.filter(pl.col(seg_col) == val)
            if s0.height + s1.height < MIN_N:
                continue
            d0 = s0.filter(pl.col("outcome_type") == "issuer_declined").height / max(s0.height, 1)
            d1 = s1.filter(pl.col("outcome_type") == "issuer_declined").height / max(s1.height, 1)
            excess = (d1 - d0) * s1.height
            by_seg.append(
                {
                    "segment": val,
                    "baseline_decline": d0,
                    "window_decline": d1,
                    "baseline_n": s0.height,
                    "window_n": s1.height,
                    "excess_declines": excess,
                }
            )
        by_seg.sort(key=lambda x: -x["excess_declines"])
        codes = (
            win.filter(pl.col("outcome_type") == "issuer_declined")
            .group_by("decline_code")
            .len()
            .sort("len", descending=True)
        )
        an = await self.analysis(
            f"payments_by_{seg_col}",
            by_seg,
            f"Issuer decline rate by {seg_col}, baseline vs window",
            [b.id],
            Window(ctx.case.baseline_start, ctx.case.window_end),
        )
        m_s0 = ctx.metric("payment success rate, baseline", r0["success"], "rate", [b.id])
        m_s1 = ctx.metric("payment success rate, window", r1["success"], "rate", [b.id])
        m_i0 = ctx.metric("issuer decline rate, baseline", r0["issuer"], "rate", [b.id])
        m_i1 = ctx.metric("issuer decline rate, window", r1["issuer"], "rate", [b.id])
        m_o0 = ctx.metric("Acme-side payment error rate, baseline", r0["ours"], "rate", [b.id])
        m_o1 = ctx.metric("Acme-side payment error rate, window", r1["ours"], "rate", [b.id])

        moved = abs(r1["success"] - r0["success"]) >= 0.02
        if not moved:
            self.add_finding(
                f"Payments look normal: success rate {pct(r0['success'])} → {pct(r1['success'])}, issuer declines "
                f"{pct(r0['issuer'])} → {pct(r1['issuer'])}, Acme-side errors {pct(r0['ours'])} → {pct(r1['ours'])}.",
                [b.id],
                [m_s0.id, m_s1.id, m_i0.id, m_i1.id, m_o0.id, m_o1.id],
                confidence=0.85,
            )
            return
        self.add_finding(
            f"Payment success fell from {pct(r0['success'])} to {pct(r1['success'])}. Issuer declines went from "
            f"{pct(r0['issuer'])} to {pct(r1['issuer'])}; errors on Acme's side went from {pct(r0['ours'])} to "
            f"{pct(r1['ours'])}.",
            [b.id],
            [m_s0.id, m_s1.id, m_i0.id, m_i1.id, m_o0.id, m_o1.id],
            confidence=0.9,
        )

        if r1["ours"] - r0["ours"] >= 0.03:
            await self.errors_spike(win, b.id, m_o0.id, m_o1.id)
        top = by_seg[0] if by_seg else None
        if top and top["excess_declines"] >= 3 and top["window_decline"] - top["baseline_decline"] >= 0.08:
            others = [x for x in by_seg[1:] if x["window_n"] >= MIN_N]
            oth0 = sum(x["baseline_decline"] * x["baseline_n"] for x in others) / max(
                sum(x["baseline_n"] for x in others), 1
            )
            oth1 = sum(x["window_decline"] * x["window_n"] for x in others) / max(
                sum(x["window_n"] for x in others), 1
            )
            label = seg_label("country", top["segment"])
            m_t0 = ctx.metric(
                f"issuer decline rate, {label}, baseline", top["baseline_decline"], "rate", [an.id]
            )
            m_t1 = ctx.metric(f"issuer decline rate, {label}, window", top["window_decline"], "rate", [an.id])
            m_x0 = ctx.metric("issuer decline rate, other countries, baseline", oth0, "rate", [an.id])
            m_x1 = ctx.metric("issuer decline rate, other countries, window", oth1, "rate", [an.id])
            code_txt = ""
            seg_codes = (
                win.filter(
                    (pl.col(seg_col) == top["segment"]) & (pl.col("outcome_type") == "issuer_declined")
                )
                .group_by("decline_code")
                .len()
                .sort("len", descending=True)
            )
            if seg_codes.height:
                c = seg_codes.row(0, named=True)
                m_c = ctx.metric(
                    f"share of {label} declines with code {c['decline_code']}",
                    c["len"] / seg_codes["len"].sum(),
                    "share",
                    [an.id],
                )
                code_txt = (
                    f" Most are “{c['decline_code']}” ({pct(m_c.value, 0)}), a code issuing banks return."
                )
            start = self._start_time(df, seg_col, top["segment"])
            when = f" It started around {start:%a %b %d %H:00} UTC." if start else ""
            self.add_finding(
                f"The declines are concentrated in cards from {label}: issuer decline rate {pct(top['baseline_decline'])} → "
                f"{pct(top['window_decline'])}, while other countries stayed at {pct(oth0)} → {pct(oth1)}.{code_txt}{when} "
                "Acme's own payment errors did not rise, so this is on the issuing banks' side.",
                [b.id, an.id],
                [m_t0.id, m_t1.id, m_x0.id, m_x1.id] + ([m_c.id] if code_txt else []),
                confidence=0.9,
            )
            self.propose(
                f"Card issuers in {label} started declining payments",
                "payment_success_rate",
                {"country": top["segment"]},
                start,
                [],
            )
        del codes

    async def errors_spike(self, win: pl.DataFrame, evid: str, m0: str, m1: str) -> None:
        err = win.filter(pl.col("outcome_type").is_in(["api_error", "invalid", "blocked"]))
        hours = err.group_by(pl.col("created").dt.truncate("1h")).len().sort("created")
        if not hours.height:
            return
        peak = hours.sort("len", descending=True).row(0, named=True)["created"]
        span = hours.filter(pl.col("len") >= 2)
        start, end = (
            (span["created"].min(), span["created"].max() + timedelta(hours=1))
            if span.height
            else (peak, peak)
        )
        an = await self.analysis("payment_errors_by_hour", hours, "Payment API errors by hour", [evid], None)
        self.add_finding(
            f"Payment API errors (not card declines) spiked between {start:%a %H:00} and {end:%H:00} UTC: something "
            "between Acme and its payment provider failed.",
            [evid, an.id],
            [m0, m1],
            kind="inference",
            confidence=0.8,
        )
        self.propose(
            "Payment API errors during a provider or integration outage",
            "payment_success_rate",
            {},
            start,
            [],
            end=end,
        )

    def _start_time(self, df: pl.DataFrame, col: str, val: Any):
        s = df.filter(pl.col(col) == val).sort("created")
        if s.height < 10:
            return None
        base = s.filter(pl.col("created") < self.ctx.case.window_start)
        p0 = base.filter(pl.col("outcome_type") == "issuer_declined").height / max(base.height, 1)
        w = s.filter(pl.col("created") >= self.ctx.case.window_start)
        x = (w["outcome_type"] == "issuer_declined").cast(pl.Float64).to_numpy()
        cs, lo, start = 0.0, 0, None
        sd = max(np.sqrt(p0 * (1 - p0)), 0.05)
        for i, v in enumerate(x):
            cs = max(0.0, cs + (v - p0) / sd - 0.5)
            if cs == 0:
                lo = i + 1
            if cs > 4:
                start = w["created"][min(lo, len(x) - 1)]
                break
        return start

    def tools(self) -> list[Tool]:
        return []
