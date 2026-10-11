"""The two runner jobs. Results and images go to blob storage under runs/<job_id>/ so the engine can poll."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import time
from typing import Any

from playwright.async_api import Browser, async_playwright

from engine.storage import get_blob_store
from runner import flows, replay

log = logging.getLogger("whydunit.runner")


async def run_flows(spec: dict[str, Any], *, max_parallel: int = 3) -> dict[str, Any]:
    job = spec["job_id"]
    flow = flows.FLOWS[spec.get("flow", "signup")]
    probes = spec.get("probes") or list(flows.MATRIX)
    store = get_blob_store()
    t0 = time.monotonic()
    results: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(max_parallel)
    async with async_playwright() as p:
        browsers: dict[str, Browser] = {}
        lock = asyncio.Lock()

        async def one(target: dict[str, Any], probe: str) -> None:
            async with sem:
                async with lock:
                    ctx = await flows.new_context(p, browsers, probe)
                page = await ctx.new_page()
                try:
                    r = await flow(page, target["url"], tag=f"{job}-{probe}")
                except Exception as e:  # noqa: BLE001
                    r = {
                        "ok": False,
                        "error": f"{type(e).__name__}: {str(e).splitlines()[0][:200]}",
                        "infra": True,
                    }
                key = f"runs/{job}/{target['id']}/{probe}.png"
                try:
                    await store.put(key, await page.screenshot(type="png"), "image/png")
                    r["screenshot_key"] = key
                except Exception:  # noqa: BLE001
                    pass
                await ctx.close()
                results.append({"target_id": target["id"], "url": target["url"], "probe": probe, **r})
                log.info("%s %s -> %s", target["id"], probe, "PASS" if r.get("ok") else "FAIL")

        try:
            await asyncio.gather(*(one(t, pr) for t in spec["targets"] for pr in probes))
        finally:
            for b in browsers.values():
                await b.close()
    out = {
        "job_id": job,
        "kind": "run-flows",
        "flow": spec.get("flow", "signup"),
        "seconds": round(time.monotonic() - t0, 1),
        "results": sorted(results, key=lambda r: (r["target_id"], r["probe"])),
    }
    await store.put(f"runs/{job}/results.json", json.dumps(out).encode(), "application/json")
    return out


async def render_replays(spec: dict[str, Any]) -> dict[str, Any]:
    job = spec["job_id"]
    store = get_blob_store()
    t0 = time.monotonic()
    out_recs = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            for rec in spec["recordings"]:
                events = rec.get("events")
                if events is None:
                    raw = await store.get(rec["events_key"])
                    events = json.loads(gzip.decompress(raw) if rec["events_key"].endswith(".gz") else raw)
                times = rec.get("times_ms") or []
                shots = await replay.render(browser, events, times)
                keys = []
                for i, (t, png) in enumerate(zip(times, shots, strict=True)):
                    key = f"runs/{job}/{rec['session_id']}/{i:03d}_{t}.png"
                    await store.put(key, png, "image/png")
                    keys.append({"t_ms": t, "key": key})
                out_recs.append({"session_id": rec["session_id"], "keyframes": keys})
        finally:
            await browser.close()
    out = {
        "job_id": job,
        "kind": "render-replay",
        "seconds": round(time.monotonic() - t0, 1),
        "recordings": out_recs,
    }
    await store.put(f"runs/{job}/results.json", json.dumps(out).encode(), "application/json")
    return out
