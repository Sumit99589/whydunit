"""The fixer: turns verdict actions into fixes, tests them, and applies them only when approved.

Code fixes: Super writes a forward fix for the culprit file (fallback: restore the file as it was before the
culprit commit), committed to a branch of acme-demo through the GitHub API, opened as a pull request with an
evidence-linked description. Vercel builds a preview; the runner re-runs the failing flow on it across the
browser matrix; the PR is marked verified only if every browser passes (Super revises up to twice). Merging
is approval-gated. Config fixes (ad budget) and the payments mitigation are approval-gated too.
Fixture worlds have no repository or account to change, so their fixes are proposals only.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from engine import db
from engine.runtime import events as ev
from engine.runtime.llm import LLM, get_llm
from engine.runtime.runner_client import RunnerClient, RunnerUnavailable
from engine.runtime.schemas import new_id
from engine.settings import env

log = logging.getLogger("whydunit.fixer")
MAX_REVISIONS = 2


class FixError(RuntimeError):
    pass


async def _emit(case_id: str, type: str, fix: dict[str, Any], note: str | None = None) -> None:
    log_ = await ev.CaseLog(case_id).init()
    await log_.emit(type, "fixer", fix=_public(fix), note=note)


def _public(fix: dict[str, Any]) -> dict[str, Any]:
    d = dict(fix)
    for k in ("created_at", "approved_at", "applied_at", "verified_at"):
        if isinstance(d.get(k), datetime):
            d[k] = d[k].isoformat()
    return d


async def save_fix(case_id: str, fix: dict[str, Any]) -> None:
    await db.execute(
        """INSERT INTO fixes (id, case_id, hypothesis_id, type, status, title, detail, pr_url, preview_url,
               approved_at, applied_at, verified_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, detail = EXCLUDED.detail, pr_url = EXCLUDED.pr_url,
             preview_url = EXCLUDED.preview_url, approved_at = EXCLUDED.approved_at, applied_at = EXCLUDED.applied_at,
             verified_at = EXCLUDED.verified_at""",
        (
            fix["id"],
            case_id,
            fix.get("hypothesis_id"),
            fix["type"],
            fix["status"],
            fix["title"],
            db.jsonb(fix["detail"]),
            fix.get("pr_url"),
            fix.get("preview_url"),
            fix.get("approved_at"),
            fix.get("applied_at"),
            fix.get("verified_at"),
        ),
    )


async def load_fix(fix_id: str) -> tuple[str, dict[str, Any]]:
    row = await db.fetchrow("SELECT * FROM fixes WHERE id = %s", (fix_id,))
    if not row:
        raise FixError("no such fix")
    return row["case_id"], dict(row)


# ------------------------------------------------------------------------------------------- GitHub helpers


class Repo:
    def __init__(self, repo: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.repo = repo or env("ACME_REPO", "Sumit99589/acme-demo")
        self.token = env("ACME_GITHUB_TOKEN") or env("GITHUB_TOKEN")
        self.transport = transport

    @property
    def available(self) -> bool:
        return bool(self.token)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=self.transport,
            timeout=30,
            headers={
                "authorization": f"Bearer {self.token}",
                "accept": "application/vnd.github+json",
                "x-github-api-version": "2022-11-28",
            },
        )

    async def file(self, path: str, ref: str) -> tuple[str, str]:
        async with self.client() as c:
            r = await c.get(f"/repos/{self.repo}/contents/{path}", params={"ref": ref})
            r.raise_for_status()
            d = r.json()
        return base64.b64decode(d["content"]).decode(), d["sha"]

    async def branch_from_main(self, branch: str) -> str:
        async with self.client() as c:
            main = (await c.get(f"/repos/{self.repo}/git/ref/heads/main")).raise_for_status().json()
            sha = main["object"]["sha"]
            r = await c.post(f"/repos/{self.repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha})
            if r.status_code not in (201, 422):  # 422: already exists
                r.raise_for_status()
        return sha

    async def put_file(self, path: str, content: str, branch: str, message: str) -> str:
        _, blob_sha = await self.file(path, branch)
        async with self.client() as c:
            r = await c.put(
                f"/repos/{self.repo}/contents/{path}",
                json={
                    "message": message,
                    "branch": branch,
                    "sha": blob_sha,
                    "content": base64.b64encode(content.encode()).decode(),
                },
            )
            r.raise_for_status()
            return r.json()["commit"]["sha"]

    async def open_pr(self, branch: str, title: str, body: str) -> dict[str, Any]:
        async with self.client() as c:
            r = await c.post(
                f"/repos/{self.repo}/pulls",
                json={"title": title, "head": branch, "base": "main", "body": body},
            )
            if r.status_code == 422:
                r = await c.get(
                    f"/repos/{self.repo}/pulls", params={"head": f"{self.repo.split('/')[0]}:{branch}"}
                )
                return r.raise_for_status().json()[0]
            return r.raise_for_status().json()

    async def comment(self, number: int, body: str) -> None:
        async with self.client() as c:
            await c.post(f"/repos/{self.repo}/issues/{number}/comments", json={"body": body})

    async def merge(self, number: int) -> str:
        async with self.client() as c:
            r = await c.put(f"/repos/{self.repo}/pulls/{number}/merge", json={"merge_method": "squash"})
            r.raise_for_status()
            return r.json()["sha"]


async def preview_url_for(sha: str, timeout_s: float = 600) -> str | None:
    """Vercel builds every push; find the preview deployment for this commit."""
    token = env("VERCEL_TOKEN")
    if not token:
        return None
    params = {"app": env("VERCEL_ACME_PROJECT", "acme-demo"), "limit": 20}
    if env("VERCEL_TEAM_ID"):
        params["teamId"] = env("VERCEL_TEAM_ID")
    deadline = asyncio.get_event_loop().time() + timeout_s
    async with httpx.AsyncClient(
        base_url="https://api.vercel.com", headers={"authorization": f"Bearer {token}"}, timeout=30
    ) as c:
        while asyncio.get_event_loop().time() < deadline:
            r = await c.get("/v6/deployments", params=params)
            for d in r.json().get("deployments", []) if r.status_code == 200 else []:
                if (d.get("meta") or {}).get("githubCommitSha") == sha and d.get(
                    "readyState", d.get("state")
                ) == "READY":
                    return f"https://{d['url']}"
            await asyncio.sleep(10)
    return None


# ------------------------------------------------------------------------------------------- proposing


async def propose(
    case_id: str,
    world: str,
    verdict: dict[str, Any],
    *,
    llm: LLM | None = None,
    repo: Repo | None = None,
    runner: RunnerClient | None = None,
) -> list[dict[str, Any]]:
    """Create a fix for each verdict action; code fixes are prepared and tested on a preview right away."""
    fixes = []
    for a in verdict.get("actions", []):
        if a["type"] == "none":
            continue
        fix = {
            "id": new_id("fix"),
            "hypothesis_id": a.get("hypothesis_id"),
            "type": a["type"],
            "title": a["title"],
            "status": "proposed",
            "detail": dict(a.get("detail") or {}),
            "pr_url": None,
            "preview_url": None,
        }
        fix["detail"]["approval_required"] = a.get("approval_required", a["type"] in ("code_pr", "config"))
        if world != "live":
            fix["status"] = "proposed_only"
            fix["detail"]["note"] = (
                "Fixture world: there is no repository or account to change, so this stays a proposal."
            )
        await save_fix(case_id, fix)
        await _emit(case_id, "fix_proposed", fix)
        fixes.append(fix)
    await ev.set_status(case_id, "fixing")
    for fix in fixes:
        if fix["type"] == "code_pr" and world == "live":
            try:
                await prepare_code_fix(
                    case_id, fix, llm=llm or get_llm(), repo=repo or Repo(), runner=runner or RunnerClient()
                )
            except Exception as e:  # noqa: BLE001 - keep the case going; the reason is shown on the board
                fix["status"], fix["detail"]["error"] = "failed", f"{type(e).__name__}: {e}"[:300]
                await save_fix(case_id, fix)
                await _emit(
                    case_id, "fix_updated", fix, f"Could not prepare the fix: {fix['detail']['error']}"
                )
    return fixes


async def write_patch(
    llm: LLM,
    current: str,
    path: str,
    suspect: dict[str, Any] | None,
    failure: str,
    before: str | None,
    attempt: int,
    feedback: str | None,
) -> tuple[str, str]:
    """Super writes the corrected file. Fallback: the file as it was before the culprit commit."""
    if llm.available():
        prompt = (
            f"File {path} in a Next.js app has a bug that breaks signup on some browsers.\n"
            f"Failure: {failure}\nSuspect: {json.dumps(suspect) if suspect else 'unknown'}\n"
            + (f"A previous attempt failed: {feedback}\n" if feedback else "")
            + "Fix it with the smallest safe change (keep the refactor's intent, add a fallback where a browser API is "
            'missing). Return JSON {"explanation": "one sentence", "content": "the complete corrected file"}.\n\n'
            f"CURRENT FILE:\n{current}"
        )
        try:
            r = await llm.chat(
                "super",
                [{"role": "user", "content": prompt}],
                reasoning=True,
                json_mode=True,
                max_tokens=6000,
                tag=f"fixer:patch:{attempt}",
            )
            d = r.json()
            if d.get("content") and d["content"] != current:
                return d["content"], str(d.get("explanation", ""))[:300]
        except Exception as e:  # noqa: BLE001
            log.warning("Super patch failed: %s", e)
    if before is not None:
        return before, "Restores the file as it was before the culprit commit (a revert of that change)."
    raise FixError("no patch could be produced")


async def prepare_code_fix(
    case_id: str, fix: dict[str, Any], *, llm: LLM, repo: Repo, runner: RunnerClient
) -> None:
    if not repo.available:
        fix["status"] = "proposed_only"
        fix["detail"]["note"] = "No GitHub token for acme-demo, so the pull request cannot be opened."
        await save_fix(case_id, fix)
        await _emit(case_id, "fix_updated", fix, fix["detail"]["note"])
        return
    d = fix["detail"]
    suspect = d.get("suspect") or {}
    path = suspect.get("file") or "app/signup/SignupForm.tsx"
    culprit = d.get("sha")
    branch = f"whydunit/fix-{fix['id'][4:]}"
    await repo.branch_from_main(branch)
    current, _ = await repo.file(path, branch)
    before = None
    if culprit:
        try:
            async with repo.client() as c:
                parent = (
                    (await c.get(f"/repos/{repo.repo}/commits/{culprit}"))
                    .raise_for_status()
                    .json()["parents"][0]["sha"]
                )
            before, _ = await repo.file(path, parent)
        except Exception:  # noqa: BLE001
            before = None
    feedback = None
    failure = (
        "The Create account button does nothing on WebKit (Safari and all iOS browsers); no request is sent."
    )
    for attempt in range(1, MAX_REVISIONS + 2):
        content, why = await write_patch(llm, current, path, suspect, failure, before, attempt, feedback)
        sha = await repo.put_file(
            path, content, branch, f"fix(signup): {why[:60] or 'restore signup on WebKit'}"
        )
        if attempt == 1:
            body = _pr_body(case_id, fix, why)
            pr = await repo.open_pr(branch, fix["title"], body)
            fix["pr_url"], d["pr_number"], d["branch"] = pr["html_url"], pr["number"], branch
        d.setdefault("attempts", []).append({"attempt": attempt, "sha": sha, "explanation": why})
        fix["status"] = "testing_preview"
        await save_fix(case_id, fix)
        await _emit(case_id, "fix_updated", fix, f"Attempt {attempt}: {why}")
        preview = await preview_url_for(sha)
        if not preview:
            fix["status"], d["note"] = (
                "awaiting_preview",
                "Vercel preview not found; verify manually before merging.",
            )
            await save_fix(case_id, fix)
            await _emit(case_id, "fix_updated", fix, d["note"])
            return
        fix["preview_url"] = preview
        try:
            res = await runner.run_flows([{"id": "preview", "url": preview}])
        except (RunnerUnavailable, TimeoutError, RuntimeError) as e:
            fix["status"], d["note"] = "awaiting_verification", f"Runner unavailable: {e}"
            await save_fix(case_id, fix)
            await _emit(case_id, "fix_updated", fix, d["note"])
            return
        failing = [r["probe"] for r in res["results"] if not r.get("ok")]
        d.setdefault("preview_runs", []).append(
            {"attempt": attempt, "results": res["results"], "backend": res.get("backend")}
        )
        if not failing:
            fix["status"], fix["verified_at"] = "verified_on_preview", datetime.now(UTC)
            await repo.comment(
                d["pr_number"],
                f"Whydunit verified this preview ({preview}) on all {len(res['results'])} "
                "browsers in the matrix: signup works everywhere.",
            )
            await save_fix(case_id, fix)
            await _emit(
                case_id, "fix_updated", fix, "Preview passes signup on every browser. Ready to merge."
            )
            return
        feedback = f"Preview still fails on {', '.join(failing)}: {res['results'][0].get('error')}"
        await _emit(case_id, "fix_updated", fix, feedback)
    fix["status"] = "failed_verification"
    await save_fix(case_id, fix)
    await _emit(case_id, "fix_updated", fix, f"Still failing after {MAX_REVISIONS} revisions; needs a human.")


def _pr_body(case_id: str, fix: dict[str, Any], why: str) -> str:
    ui = env("WHYDUNIT_UI_URL", "")
    d = fix["detail"]
    s = d.get("suspect") or {}
    return (
        f"**Opened by Whydunit** for case [{case_id}]({ui}/cases/{case_id}).\n\n"
        f"**Why:** deployment `{(d.get('sha') or '')[:7]}` broke signup on WebKit. "
        + (f"It added `{s.get('api')}` in `{s.get('file')}` with no fallback; {s.get('note')}." if s else "")
        + f"\n\n**This change:** {why}\n\n"
        "**Verification:** Whydunit re-runs the signup flow on this branch's Vercel preview in Chromium, WebKit "
        "(desktop and iPhone), Chrome on Pixel and Firefox, and comments here with the result.\n\n"
        "Merging is up to you (or the Approve button on the case board)."
    )


# ------------------------------------------------------------------------------------------- approving


async def approve(fix_id: str) -> dict[str, Any]:
    case_id, row = await load_fix(fix_id)
    fix = {**row, "detail": dict(row["detail"])}
    if fix["status"] in ("applied", "merged", "monitoring", "recovered"):
        return fix
    if fix["status"] == "proposed_only":
        raise FixError("this fix is a proposal only (fixture world or no access)")
    now = datetime.now(UTC)
    fix["approved_at"] = now
    if fix["type"] == "code_pr":
        if fix["status"] not in ("verified_on_preview", "awaiting_verification", "awaiting_preview"):
            raise FixError(f"the pull request is not ready to merge (status {fix['status']})")
        sha = await Repo().merge(int(fix["detail"]["pr_number"]))
        fix["detail"]["merge_sha"] = sha
        note = "Merged. Vercel deploys main to production."
    elif fix["type"] == "config":
        d = fix["detail"]
        from engine.mock_ads import store

        res = await store.set_budget(
            str(d["campaign_id"]),
            float(d["to"]),
            user_email="whydunit-fix@acme-notes.test",
            client_type="GOOGLE_ADS_API",
        )
        fix["detail"]["change_event_id"] = res["change_event_id"]
        note = f"Budget restored to ${float(d['to']):.0f} (simulated ad platform)."
    else:
        from simulator import state

        mitig = await state.get("mitigations", {})
        mitig["payment_declines"] = now.isoformat()
        await state.put("mitigations", mitig)
        note = "Mitigation switched on in the simulator (retries and a local payment method for the affected cards)."
    fix["status"], fix["applied_at"] = "monitoring", now
    await save_fix(case_id, fix)
    await _emit(case_id, "fix_updated", fix, note)
    await ev.set_status(case_id, "verifying")
    log_ = await ev.CaseLog(case_id).init()
    await log_.emit("verifying", "whydunit", fix_id=fix_id)
    return fix
