"""Launch browser-runner jobs (flow checks, replay keyframes) and wait for their results.

Backends, in order of preference from config/runner.yaml:
  nebius_job      `nebius ai job create` with the runner image; results polled from object storage
  github_actions  dispatch the runner-job workflow; results from object storage or the run's artifact
  local           run in-process (development only, one browser, capped by the caller)
  fixture         recorded results stored in a fixture world
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import shutil
import time
import uuid
import zipfile
from typing import Any, Protocol

import httpx

from engine.settings import env, load_config
from engine.storage import LocalBlobStore, get_blob_store

log = logging.getLogger("whydunit.runner_client")


class RunnerUnavailable(RuntimeError):
    pass


class Backend(Protocol):
    name: str

    async def available(self) -> bool: ...
    async def submit(self, kind: str, spec: dict[str, Any]) -> dict[str, Any]: ...


def new_job_id(prefix: str = "job") -> str:
    return f"{prefix}-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


async def _poll_results(job_id: str, timeout_s: float, interval_s: float, fallback=None) -> dict[str, Any]:
    store = get_blob_store()
    key = f"runs/{job_id}/results.json"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await store.exists(key):
            return json.loads(await store.get(key))
        if fallback is not None:
            got = await fallback()
            if got is not None:
                return got
        await asyncio.sleep(interval_s)
    raise TimeoutError(f"runner job {job_id} produced no results in {timeout_s:.0f}s")


class NebiusJob:
    name = "nebius_job"

    def __init__(self) -> None:
        self.cfg = load_config("runner")

    async def available(self) -> bool:
        # Results travel through object storage, so a shared bucket is required too.
        return bool(shutil.which("nebius") and env("NEBIUS_PROJECT_ID") and env("S3_BUCKET"))

    async def submit(self, kind: str, spec: dict[str, Any]) -> dict[str, Any]:
        n, job = self.cfg["nebius"], spec["job_id"]
        cmd = [
            "nebius",
            "ai",
            "job",
            "create",
            "--name",
            f"whydunit-{job}"[:60],
            "--image",
            self.cfg["image"],
            "--container-command",
            "python",
            "--args",
            f"-m runner {kind}",
            "--platform",
            n["platform"],
            "--preset",
            n["preset"],
            "--timeout",
            n["timeout"],
            "--disk-size",
            n["disk_size"],
            "--parent-id",
            env("NEBIUS_PROJECT_ID") or "",
            "--env",
            f"RUNNER_SPEC={json.dumps(spec)}",
            "--async",
            "--format",
            "jsonpath={.resource_id}",
        ]
        for var in ("S3_ENDPOINT_URL", "S3_REGION", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
            if env(var):
                cmd += ["--env", f"{var}={env(var)}"]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"nebius ai job create failed: {err.decode()[-400:]}")
        nebius_job_id = out.decode().strip()
        log.info("nebius job %s started for %s", nebius_job_id, job)
        res = await _poll_results(job, self.cfg["poll"]["timeout_s"], self.cfg["poll"]["interval_s"])
        res["backend"] = {
            "name": self.name,
            "nebius_job_id": nebius_job_id,
            "image": self.cfg["image"],
            "platform": n["platform"],
            "preset": n["preset"],
        }
        return res


class GitHubActions:
    name = "github_actions"

    def __init__(self) -> None:
        self.cfg = load_config("runner")["github"]
        self.poll = load_config("runner")["poll"]

    def _token(self) -> str | None:
        return env("WHYDUNIT_GITHUB_TOKEN") or env("GITHUB_TOKEN_WHYDUNIT")

    async def available(self) -> bool:
        return bool(self._token())

    async def submit(self, kind: str, spec: dict[str, Any]) -> dict[str, Any]:
        headers = {"authorization": f"Bearer {self._token()}", "accept": "application/vnd.github+json"}
        repo, job = self.cfg["repo"], spec["job_id"]
        async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers, timeout=30) as gh:
            r = await gh.post(
                f"/repos/{repo}/actions/workflows/{self.cfg['workflow']}/dispatches",
                json={
                    "ref": self.cfg["ref"],
                    "inputs": {"kind": kind, "job_id": job, "spec": json.dumps(spec)},
                },
            )
            r.raise_for_status()

            async def from_artifact() -> dict[str, Any] | None:
                a = await gh.get(
                    f"/repos/{repo}/actions/artifacts", params={"name": f"runner-{job}", "per_page": 1}
                )
                arts = a.json().get("artifacts", []) if a.status_code == 200 else []
                if not arts:
                    return None
                z = await gh.get(arts[0]["archive_download_url"], follow_redirects=True)
                if z.status_code != 200:
                    return None
                zf = zipfile.ZipFile(io.BytesIO(z.content))
                store = get_blob_store()
                for name in zf.namelist():  # mirror images into our own store so evidence links work
                    if not name.endswith("/"):
                        await store.put(f"runs/{job}/{name.split(f'runs/{job}/')[-1]}", zf.read(name))
                return json.loads(zf.read(next(n for n in zf.namelist() if n.endswith("results.json"))))

            res = await _poll_results(job, self.poll["timeout_s"], self.poll["interval_s"] * 2, from_artifact)
        res["backend"] = {"name": self.name, "workflow": self.cfg["workflow"]}
        return res


class Local:
    """In-process runner for development. The caller must already be inside a memory-capped scope."""

    name = "local"

    async def available(self) -> bool:
        return env("WHYDUNIT_RUNNER") == "local"

    async def submit(self, kind: str, spec: dict[str, Any]) -> dict[str, Any]:
        from runner import jobs

        fn = jobs.run_flows if kind == "run-flows" else jobs.render_replays
        if kind == "run-flows":
            res = await fn(spec, max_parallel=load_config("runner")["local"]["max_parallel"])
        else:
            res = await fn(spec)
        res["backend"] = {"name": self.name}
        return res


class Fixture:
    """Flow results recorded in a fixture world (no browsers)."""

    name = "fixture"

    def __init__(self, world: Any):
        self.world = world

    async def available(self) -> bool:
        return True

    async def submit(self, kind: str, spec: dict[str, Any]) -> dict[str, Any]:
        if kind != "run-flows":
            raise RunnerUnavailable("fixture worlds have no keyframe renderer; use heuristics")
        rows = await self.world.flow_results([t["id"] for t in spec["targets"]], spec.get("probes"))
        results = [
            {
                "target_id": r["deployment_id"],
                "url": r["url"],
                "probe": r["probe"],
                "ok": r["ok"],
                "ms": r["ms"],
                "error": r["error"],
                "screenshot_key": r["screenshot_ref"],
                "recorded": True,
            }
            for r in rows
        ]
        return {
            "job_id": spec["job_id"],
            "kind": kind,
            "results": results,
            "backend": {"name": self.name, "note": "recorded flow results from the fixture world"},
        }


class RunnerClient:
    def __init__(self, backends: list[Backend] | None = None):
        if backends is None:
            order = load_config("runner")["backends"]
            make = {"nebius_job": NebiusJob, "github_actions": GitHubActions, "local": Local}
            backends = [make[b]() for b in order if b in make]
        self.backends = backends

    async def pick(self) -> Backend:
        for b in self.backends:
            if await b.available():
                return b
        raise RunnerUnavailable(
            "no runner backend available (needs a Nebius project + bucket, a GitHub token, "
            "or WHYDUNIT_RUNNER=local)"
        )

    async def run_flows(
        self, targets: list[dict[str, str]], probes: list[str] | None = None, flow: str = "signup"
    ) -> dict[str, Any]:
        spec = {"job_id": new_job_id("flows"), "flow": flow, "targets": targets, "probes": probes}
        return await (await self.pick()).submit("run-flows", spec)

    async def render_replays(self, recordings: list[dict[str, Any]]) -> dict[str, Any]:
        spec = {"job_id": new_job_id("replay"), "recordings": recordings}
        return await (await self.pick()).submit("render-replay", spec)

    async def describe(self) -> list[dict[str, Any]]:
        return [{"backend": b.name, "available": await b.available()} for b in self.backends]


def is_local_store() -> bool:
    return isinstance(get_blob_store(), LocalBlobStore)
