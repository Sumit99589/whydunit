"""The Deploy detective: which deployment broke it, on which browsers, and which lines?"""

from __future__ import annotations

import re
from typing import Any

from engine.agents.base import Detective, Tool, seg_label
from engine.connectors.base import Artifact, Window
from engine.runtime.runner_client import Fixture, RunnerClient, RunnerUnavailable

# Web APIs that some engines lack (Playwright 1.63 probe, 2026-10-11; see DECISIONS D15).
ENGINE_GAPS = {
    "requestIdleCallback": {
        "missing_in": ["webkit"],
        "note": "WebKit (Safari, all iOS browsers) has no requestIdleCallback",
    },
    "cancelIdleCallback": {"missing_in": ["webkit"], "note": "WebKit has no cancelIdleCallback"},
    "scheduler.postTask": {"missing_in": ["webkit"], "note": "WebKit has no scheduler.postTask"},
    "navigator.userAgentData": {
        "missing_in": ["webkit", "firefox"],
        "note": "Only Chromium has navigator.userAgentData",
    },
}
PROBE_ENGINE = {
    "chromium-desktop": "chromium",
    "chromium-mobile": "chromium",
    "webkit-desktop": "webkit",
    "webkit-mobile": "webkit",
    "firefox-desktop": "firefox",
}
PROBE_LABEL = {
    "chromium-desktop": "Chrome desktop",
    "chromium-mobile": "Chrome on Pixel",
    "webkit-desktop": "Safari desktop",
    "webkit-mobile": "Safari on iPhone",
    "firefox-desktop": "Firefox desktop",
}


def suspect_lines(diff: str) -> list[dict[str, Any]]:
    """Added lines that use an engine-specific API, with file and new-file line number."""
    out, file, line_no = [], None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            file = raw[6:] if raw.startswith("+++ b/") else raw[4:]
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) - 1 if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            line_no += 1
            for api, info in ENGINE_GAPS.items():
                if api in raw:
                    out.append({"file": file, "line": line_no, "code": raw[1:].strip(), "api": api, **info})
        elif not raw.startswith("-"):
            line_no += 1
    return out


class DeployDetective(Detective):
    def __init__(self, ctx):
        super().__init__(
            ctx,
            name="deploy",
            title="Deploy detective",
            mission="You own deployments: which production deploy in the window broke a user flow, on "
            "which browsers, and which lines of its diff are responsible.",
        )
        self.runner = None

    def _runner(self) -> RunnerClient:
        if self.runner is None:
            if self.ctx.registry.mode == "fixture":
                self.runner = RunnerClient([Fixture(self.ctx.registry.connectors[0])])
            else:
                self.runner = RunnerClient()
        return self.runner

    async def playbook(self) -> None:
        ctx = self.ctx
        dep = await self.fetch("deploys", Window(ctx.case.baseline_start, ctx.case.window_end))
        if dep is None:
            return
        rows = sorted(dep.frame.to_dicts(), key=lambda r: r["created_at"])
        if not rows:
            self.add_finding(
                "No production deployments in the window, so no deploy can be the cause.",
                [dep.id],
                [],
                confidence=0.8,
            )
            return
        before = [r for r in rows if r["created_at"] < ctx.case.window_start]
        targets = (before[-2:] + [r for r in rows if r["created_at"] >= ctx.case.window_start])[:10]
        m_n = ctx.metric("production deployments tested", len(targets), "count", [dep.id])
        await self.emit(
            "tool_call",
            tool="run_flows",
            args={"flow": "signup", "deployments": [t["id"] for t in targets], "matrix": list(PROBE_LABEL)},
            by="playbook",
        )
        try:
            res = await self._runner().run_flows([{"id": t["id"], "url": t["url"]} for t in targets])
        except (RunnerUnavailable, TimeoutError, RuntimeError) as e:
            self.cannot.append(_cd("flow_runs", str(e)))
            self.add_finding(
                f"Found {len(targets)} production deployments in the window but could not run the signup "
                "flow against them (no browser runner available).",
                [dep.id],
                [m_n.id],
                confidence=0.6,
            )
            return
        backend = res.get("backend", {})
        await self.emit(
            "tool_result", tool="run_flows", result={"backend": backend, "results": len(res["results"])}
        )
        by_dep: dict[str, dict[str, dict[str, Any]]] = {}
        for r in res["results"]:
            by_dep.setdefault(r["target_id"], {})[r["probe"]] = r
        run_ev = await self.analysis(
            "flow_runs",
            res["results"],
            f"Signup flow on {len(targets)} deployments × {len(PROBE_LABEL)} browsers via {backend.get('name')}"
            + (" (Nebius Serverless Job)" if backend.get("name") == "nebius_job" else ""),
            [dep.id],
            Window(ctx.case.baseline_start, ctx.case.window_end),
            backend=backend,
        )
        self.checked.append(f"signup flow on {len(targets)} deployments via {backend.get('name')}")

        first_bad, prev_ok = None, None
        for t in targets:
            results = by_dep.get(t["id"], {})
            failing = [p for p, r in results.items() if not r.get("ok") and not r.get("infra")]
            if failing and first_bad is None:
                first_bad = (t, failing, results)
                break
            if results and not failing:
                prev_ok = t
        if first_bad is None:
            self.add_finding(
                f"The signup flow passes on every browser for all {len(targets)} production deployments in the window, "
                "so no deploy broke signup.",
                [dep.id, run_ev.id],
                [m_n.id],
                confidence=0.85,
            )
            return
        bad, failing, results = first_bad
        passing = [p for p in results if p not in failing]
        engines = sorted({PROBE_ENGINE[p] for p in failing})
        ok_engines = sorted({PROBE_ENGINE[p] for p in passing} - set(engines))
        err = results[failing[0]].get("error") or ""
        shot = results[failing[0]].get("screenshot_key")
        arts = (
            [
                Artifact(
                    type="screenshot",
                    ref=shot,
                    caption=f"{PROBE_LABEL[failing[0]]} after tapping Create account",
                    meta={"deployment": bad["id"]},
                )
            ]
            if shot
            else []
        )
        claim = (
            f"Deployment {bad['git_sha'][:7]} (“{bad['commit_message']}”, {bad['created_at']:%a %b %d %H:%M} UTC) is "
            f"the first that breaks signup: it fails on {', '.join(PROBE_LABEL[p] for p in failing)} and passes on "
            f"{', '.join(PROBE_LABEL[p] for p in passing)}"
            + (
                f"; the previous deployment {prev_ok['git_sha'][:7]} passes on every browser."
                if prev_ok
                else "."
            )
        )
        if "no request to /api/signup" in err:
            claim += " On the failing browsers the button press never even sends the signup request."
        bad_ev = await self.analysis(
            "first_failing_deployment",
            [
                {
                    "deployment": bad["id"],
                    "sha": bad["git_sha"],
                    "failing": failing,
                    "passing": passing,
                    "error": err,
                }
            ],
            f"First failing deployment {bad['git_sha'][:7]}: fails on {', '.join(engines)}",
            [dep.id, run_ev.id],
            None,
        )
        bad_ev.artifacts.extend(arts)
        self.add_finding(claim, [dep.id, run_ev.id, bad_ev.id], [], confidence=0.95)
        self.bad = bad

        # The diff against the previous deployment.
        diff_info = None
        base_sha = prev_ok["git_sha"] if prev_ok else (before[-1]["git_sha"] if before else bad["git_sha"])
        try:
            compare = self.ctx.registry.find("compare")
            await self.emit(
                "tool_call",
                tool="git_compare",
                args={"base": base_sha[:7], "head": bad["git_sha"][:7]},
                by="playbook",
            )
            diff_info = await compare(base_sha, bad["git_sha"])
        except Exception as e:  # noqa: BLE001 - no diff source: say so and carry on
            self.cannot.append(_cd("code_diff", f"could not fetch the diff: {e}"))
        suspects = suspect_lines(diff_info["diff"]) if diff_info else []
        if diff_info:
            diff_ev = await self.analysis(
                "suspect_diff",
                suspects or [{"note": "no engine-specific API in the added lines"}],
                f"Diff {base_sha[:7]}…{bad['git_sha'][:7]}: {len(diff_info['files'])} file(s) changed"
                + (f"; suspect: {suspects[0]['api']} in {suspects[0]['file']}" if suspects else ""),
                [dep.id],
                None,
                base=base_sha,
                head=bad["git_sha"],
            )
            diff_ev.artifacts.append(
                Artifact(
                    type="diff",
                    ref=diff_info.get("url"),
                    caption=f"{base_sha[:7]}…{bad['git_sha'][:7]}",
                    meta={"diff": diff_info["diff"][:6000], "suspects": suspects},
                )
            )
            relevant = [
                s
                for s in suspects
                if set(s["missing_in"]) & set(engines) and not set(s["missing_in"]) & set(ok_engines)
            ]
            if relevant:
                s = relevant[0]
                self.add_finding(
                    f"The diff adds {s['api']} in {s['file']} with no fallback. {s['note']}, which "
                    f"matches exactly the browsers that fail, so the submit button is never enabled there.",
                    [diff_ev.id, bad_ev.id, run_ev.id],
                    [],
                    kind="inference",
                    confidence=0.9,
                )
                self.suspect = s
            elif suspects or diff_info["files"]:
                self.add_finding(
                    f"The diff of {bad['git_sha'][:7]} touches {', '.join(f['filename'] for f in diff_info['files'][:3])}; "
                    "no known engine-specific API explains the failure, so the cause needs a closer look.",
                    [diff_ev.id, bad_ev.id],
                    [],
                    kind="inference",
                    confidence=0.5,
                )
        await self.read_screenshot(shot, failing, bad_ev.id)
        seg = {"engine": engines[0]} if len(engines) == 1 else {"engine": engines}
        self.propose(
            f"Deployment {bad['git_sha'][:7]} broke signup on {' and '.join(seg_label('engine', e) for e in engines)}",
            "signup_rate",
            seg,
            bad["created_at"],
            [],
        )

    async def answer_deploy_around(self, q):
        """Did a deployment around the given time break the flow for the segment?"""
        from datetime import datetime, timedelta

        from engine.runtime.schemas import Answer

        at = datetime.fromisoformat(q.params["at"]) if isinstance(q.params["at"], str) else q.params["at"]
        bad = getattr(self, "bad", None)
        if bad is None:
            tested = any("signup flow on" in c for c in self.checked)
            return Answer(
                question_id=q.id,
                detective=self.name,
                verdict="contradicts" if tested else "cannot_determine",
                text="No deployment in the window breaks signup on any browser."
                if tested
                else "I could not test the deployments.",
            )
        near = abs(bad["created_at"] - at) <= timedelta(hours=6)
        return Answer(
            question_id=q.id,
            detective=self.name,
            verdict="supports" if near else "neutral",
            findings=[f for f in self.findings if f.status == "accepted"][:1],
            text=(
                f"Yes: deployment {bad['git_sha'][:7]} went out at {bad['created_at']:%a %H:%M} UTC and breaks "
                "signup on those browsers."
                if near
                else f"The only breaking deployment ({bad['git_sha'][:7]}) is not close to that time."
            ),
        )

    async def read_screenshot(self, key: str | None, failing: list[str], evid: str) -> None:
        """Nemotron Nano Omni reads the failure screenshot (when images and a model are available)."""
        if not key or not self.ctx.llm.available():
            return
        from engine.storage import get_blob_store

        try:
            png = await get_blob_store().get(key)
        except Exception:  # noqa: BLE001 - recorded fixture screenshots may not exist as files
            return
        r = await self.ctx.llm.describe_images(
            "This is a screenshot taken right after a test pressed the 'Create account' button on a signup page in "
            f"{PROBE_LABEL[failing[0]]}. In one or two sentences: what is visible, is the form still shown, is there any "
            "error message, and does anything cover the button?",
            [png],
            meter=self.ctx.meter,
            tag="deploy:omni",
        )
        await self.emit("tool_result", tool="read_screenshot", result={"omni": r.content[:400]})
        self.add_finding(
            f"Screenshot read by Nemotron Nano Omni: {r.content.strip()[:300]}",
            [evid],
            [],
            kind="observed",
            confidence=0.7,
        )

    def tools(self) -> list[Tool]:
        async def run_flow(deployment_url: str, probes: list[str] | None = None):
            res = await self._runner().run_flows([{"id": "adhoc", "url": deployment_url}], probes)
            ev = await self.analysis(
                "adhoc_flow_" + deployment_url[-20:],
                res["results"],
                f"Ad-hoc signup flow on {deployment_url}",
                list(self.ctx.evidence)[:1],
                None,
            )
            return {
                "evidence_id": ev.id,
                "results": [{k: r.get(k) for k in ("probe", "ok", "error")} for r in res["results"]],
            }

        return [
            Tool(
                "run_flow",
                "Run the signup flow on one deployment URL across browsers.",
                {
                    "type": "object",
                    "properties": {
                        "deployment_url": {"type": "string"},
                        "probes": {"type": "array", "items": {"type": "string", "enum": list(PROBE_LABEL)}},
                    },
                    "required": ["deployment_url"],
                },
                run_flow,
            )
        ]


def _cd(kind: str, reason: str):
    from engine.runtime.schemas import CannotDetermine

    return CannotDetermine(kind=kind, reason=reason)
