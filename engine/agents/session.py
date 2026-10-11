"""The Session detective: watch what failing users actually experienced, frame by frame."""

from __future__ import annotations

import random
from typing import Any

import polars as pl

from engine.agents.base import Detective, Tool, seg_label
from engine.analysis.sessions import analyze, summarize
from engine.connectors.base import Artifact
from engine.runtime.runner_client import Fixture, RunnerClient, RunnerUnavailable

MAX_FAILED, MAX_CONTROLS = 10, 3


class SessionDetective(Detective):
    def __init__(self, ctx):
        super().__init__(
            ctx,
            name="session",
            title="Session detective",
            mission="You own session recordings: pick failed signups in the hardest-hit segment and a few "
            "healthy controls, and describe what the users experienced.",
        )

    async def playbook(self) -> None:
        ctx = self.ctx
        b = await self.fetch("sessions", ctx.case_window, {"has_replay": True})
        if b is None:
            return
        df = b.frame.with_columns(pl.col("started_at").dt.convert_time_zone("UTC"))
        if "engine" not in df.columns:
            from engine.analysis.data import engine_expr

            df = df.with_columns(engine_expr().alias("engine"))
        win = df.filter(
            (pl.col("started_at") >= ctx.case.window_start) & (pl.col("started_at") < ctx.case.window_end)
        )
        failed = win.filter(pl.col("signup_started") & ~pl.col("signup_completed"))
        ok = win.filter(pl.col("signup_completed"))
        if failed.height == 0:
            self.add_finding(
                "No recorded sessions in the window show a failed signup attempt.", [b.id], [], confidence=0.6
            )
            return
        # Hardest-hit segment: where failed attempts are most over-represented among recorded attempts.
        seg_dim, seg_val = "engine", None
        attempts = win.filter(pl.col("signup_started"))
        best = 0.0
        for dim in ("engine", "device", "os", "country"):
            if dim not in attempts.columns:
                continue
            g = attempts.group_by(dim).agg(
                pl.len().alias("n"), (~pl.col("signup_completed")).sum().alias("fail")
            )
            for r in g.to_dicts():
                if r["n"] >= 3 and r["fail"] / r["n"] > best + 0.05:
                    best, seg_dim, seg_val = r["fail"] / r["n"], dim, r[dim]
        rng = random.Random(7)
        pool = failed.filter(pl.col(seg_dim) == seg_val) if seg_val is not None else failed
        picks = rng.sample(pool["session_id"].to_list(), min(MAX_FAILED, pool.height))
        controls = rng.sample(ok["session_id"].to_list(), min(MAX_CONTROLS, ok.height))
        get = self.ctx.registry.find("recording")
        await self.emit(
            "tool_call",
            tool="session_heuristics",
            args={"failed": len(picks), "controls": len(controls), "segment": {seg_dim: seg_val}},
            by="playbook",
        )
        fr, cr, recs = [], [], {}
        for sid in picks + controls:
            try:
                events = await get(sid)
            except Exception:  # noqa: BLE001
                continue
            recs[sid] = events
            (fr if sid in picks else cr).append({"session_id": sid, **analyze(events)})
        if not fr:
            self.cannot.append(_cd("recordings", "recordings could not be loaded"))
            return
        sf, sc = summarize(fr), summarize(cr)
        an = await self.analysis(
            "session_heuristics",
            [{k: v for k, v in r.items() if k != "keyframe_times_ms"} for r in fr + cr],
            f"{len(fr)} failed-signup recordings in {seg_label(seg_dim, seg_val)} and {len(cr)} "
            "successful controls, analysed for rage clicks, dead clicks and abandonment",
            [b.id],
            ctx.case_window,
            segment={seg_dim: seg_val},
        )
        await self.emit("tool_result", tool="session_heuristics", result={"failed": sf, "controls": sc})
        m_n = ctx.metric("failed-signup recordings reviewed", len(fr), "count", [an.id])
        m_rage = ctx.metric("failed recordings with rage clicks", sf["with_rage_clicks"], "count", [an.id])
        m_dead = ctx.metric("failed recordings with dead clicks", sf["with_dead_clicks"], "count", [an.id])
        m_ab = ctx.metric(
            "failed recordings that typed then abandoned", sf["form_abandoned"], "count", [an.id]
        )
        m_cn = ctx.metric("successful control recordings reviewed", len(cr), "count", [an.id])
        top_el = next(iter(sf["rage_elements"]), None)
        el_txt = f" on the “{top_el}” button" if top_el else ""
        self.add_finding(
            f"In {len(fr)} recorded failed signups from {seg_label(seg_dim, seg_val)}, {sf['with_dead_clicks']} show dead "
            f"clicks and {sf['with_rage_clicks']} show rage clicks{el_txt}: the visitor filled in the form, pressed the "
            f"button, nothing changed, and pressed again. {sf['form_abandoned']} gave up after typing. In the {len(cr)} "
            "successful control session(s) the same press went straight to onboarding.",
            [b.id, an.id],
            [m_n.id, m_rage.id, m_dead.id, m_ab.id, m_cn.id],
            confidence=0.9,
        )
        await self.describe_frames(fr, recs, an.id)

    async def describe_frames(self, results: list[dict[str, Any]], recs: dict[str, list], evid: str) -> None:
        """Runner renders keyframes; Nemotron Nano Omni says what the user saw (when both are available)."""
        if self.ctx.registry.mode == "fixture" or not self.ctx.llm.available():
            return
        rage = [r for r in results if r["rage_bursts"]][:3]
        if not rage:
            return
        client = RunnerClient() if self.ctx.registry.mode != "fixture" else RunnerClient([Fixture(None)])
        try:
            await self.emit(
                "tool_call",
                tool="render_keyframes",
                args={"sessions": [r["session_id"] for r in rage]},
                by="playbook",
            )
            res = await client.render_replays(
                [
                    {
                        "session_id": r["session_id"],
                        "events": recs[r["session_id"]],
                        "times_ms": r["keyframe_times_ms"][-6:],
                    }
                    for r in rage
                ]
            )
        except (RunnerUnavailable, TimeoutError, RuntimeError) as e:
            self.cannot.append(_cd("keyframes", str(e)))
            return
        from engine.storage import get_blob_store

        store = get_blob_store()
        for rec in res["recordings"][:2]:
            frames = [await store.get(k["key"]) for k in rec["keyframes"][-4:]]
            r = await self.ctx.llm.describe_images(
                "These are consecutive frames from a recording of a visitor on a signup page (oldest first). The orange "
                "dot is their finger or cursor. Describe in two sentences what the visitor did and whether the page "
                "reacted.",
                frames,
                meter=self.ctx.meter,
                tag="session:omni",
            )
            ev = await self.analysis(
                f"keyframes_{rec['session_id']}", rec["keyframes"], "Rendered keyframes", [evid], None
            )
            ev.artifacts.extend(
                Artifact(type="keyframe", ref=k["key"], caption=f"t+{k['t_ms']}") for k in rec["keyframes"]
            )
            self.add_finding(
                f"Nemotron Nano Omni, watching session {rec['session_id']}: {r.content.strip()[:350]}",
                [ev.id, evid],
                [],
                confidence=0.75,
            )

    def tools(self) -> list[Tool]:
        return []


def _cd(kind: str, reason: str):
    from engine.runtime.schemas import CannotDetermine

    return CannotDetermine(kind=kind, reason=reason)
