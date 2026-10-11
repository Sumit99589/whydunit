"""One simulator tick: advance the live Acme world from the last tick to now, touching real systems.

    uv run python -m simulator.tick                 # full tick (GitHub Actions)
    uv run python -m simulator.tick --skip-browsers # no Playwright (local dry run)

Each tick: fire due incidents -> probe production signup across browsers -> advance the simulated ad
platform -> generate visitor journeys for the window -> run their signups and checkouts through Acme's
real API (real Stripe test-mode payments) -> send their events through the real ingest API -> write
support tickets and reviews -> drive a few real recorded browser sessions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import numpy as np

from engine import db
from engine.mock_ads import store as ads
from engine.mock_ads.model import simulate
from engine.projects import create_project
from engine.settings import ROOT, env
from engine.world.model import PROBES, Conditions, Journey, WorldModel
from simulator import state, voice
from simulator.schedule import Incident, Schedule, load_schedule
from simulator.systems import Acme, EngineIngest, insert_review, insert_ticket_direct, journey_events

log = logging.getLogger("whydunit.sim")
GROUND_TRUTH_PATH = ROOT / "simulator" / "ground_truth.json"


# ------------------------------------------------------------------------------------------- incidents


async def merge_branch(action: dict[str, Any]) -> dict[str, Any]:
    """Open a PR for the prepared branch in acme-demo and merge it (Vercel then deploys main)."""
    token, repo = env("ACME_GITHUB_TOKEN") or env("GITHUB_TOKEN"), env("ACME_REPO", "Sumit99589/acme-demo")
    if not token:
        raise RuntimeError("ACME_GITHUB_TOKEN not set")
    headers = {"authorization": f"Bearer {token}", "accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers, timeout=30) as gh:
        r = await gh.post(
            f"/repos/{repo}/pulls",
            json={
                "title": action.get("pr_title", "refactor"),
                "head": action["merge_branch"],
                "base": "main",
                "body": "Improves INP on the signup page by deferring form hydration until the browser is idle.",
            },
        )
        if r.status_code == 422 and "already exists" in r.text:
            r = await gh.get(
                f"/repos/{repo}/pulls", params={"head": f"{repo.split('/')[0]}:{action['merge_branch']}"}
            )
            pr = r.json()[0]
        else:
            r.raise_for_status()
            pr = r.json()
        m = await gh.put(f"/repos/{repo}/pulls/{pr['number']}/merge", json={"merge_method": "merge"})
        m.raise_for_status()
        return {"pr_url": pr["html_url"], "pr_number": pr["number"], "merge_sha": m.json().get("sha")}


async def fire_incident(inc: Incident, now: datetime) -> dict[str, Any]:
    if inc.type == "deploy_bug":
        return await merge_branch(inc.action)
    if inc.type == "ads_budget_cap":
        return await ads.set_budget(
            inc.action["campaign_id"],
            float(inc.action["new_daily_budget"]),
            user_email=inc.action["user_email"],
            client_type=inc.action["client_type"],
            at=now,
        )
    if inc.type == "payment_declines":
        return {"country": inc.action["country"], "decline_rate": inc.action["decline_rate"]}
    raise ValueError(f"unknown incident type {inc.type}")


async def update_ground_truth(
    schedule: Schedule, start: datetime, fired: dict[str, Any], mitigations: dict[str, str]
) -> dict[str, Any]:
    gt = {
        "simulator_start": start.isoformat(),
        "note": "Written by the live simulator. Times are UTC. Used to score the live case.",
        "incidents": [],
    }
    for inc in schedule.incidents:
        f = fired.get(inc.id)
        end = inc.ends(start)
        gt["incidents"].append(
            {
                "id": inc.id,
                "type": inc.type,
                "description": inc.description,
                "affects": inc.affects,
                "scheduled_at": inc.starts(start).isoformat(),
                "fired_at": f["at"] if f else None,
                "details": f.get("details") if f else None,
                "scheduled_end": end.isoformat() if end else None,
                "mitigated_at": mitigations.get(inc.id),
            }
        )
    await state.put("ground_truth", gt)
    return gt


def payment_declines_active(
    schedule: Schedule, start: datetime, fired: dict[str, Any], mitigations: dict[str, str], t: datetime
) -> dict[str, float]:
    out: dict[str, float] = {}
    for inc in schedule.incidents:
        if inc.type != "payment_declines" or inc.id not in fired or inc.id in mitigations:
            continue
        end = inc.ends(start)
        if t >= inc.starts(start) and (end is None or t < end):
            out[inc.action["country"]] = float(inc.action["decline_rate"])
    return out


# ------------------------------------------------------------------------------------------- journeys


async def run_journeys(journeys: list[Journey], acme: Acme, rng: random.Random) -> dict[str, int]:
    """Signups and checkouts go through Acme's real API; the payment event reflects Stripe's real answer."""
    stats = {"signups": 0, "checkouts": 0, "paid": 0, "declined": 0, "errors": 0}
    for j in journeys:
        if not j.signed_up:
            continue
        first = rng.choice(voice.FIRST)
        email = f"{first.lower()}.{j.visitor_id[-8:]}@example.com"
        try:
            if acme.available:
                user_id = await acme.signup(first, email, j.country)
            else:
                user_id = f"u_{j.visitor_id[-16:]}"
                await db.execute(
                    "INSERT INTO acme.users (id, email, name, country, created_at, synthetic) "
                    "VALUES (%s,%s,%s,%s,%s,true) ON CONFLICT DO NOTHING",
                    (user_id, email, first, j.country, j.events[-1].ts),
                )
        except httpx.HTTPError as e:
            log.warning("signup call failed: %s", e)
            stats["errors"] += 1
            continue
        stats["signups"] += 1
        for e in j.events:
            if e.name == "signup_completed":
                e.props["user_id"] = user_id
        if not j.checkout:
            continue
        stats["checkouts"] += 1
        if acme.available:
            try:
                res = await acme.checkout(user_id, email, j.payment_method or "pm_card_visa", j.country)
            except httpx.HTTPError as e:
                log.warning("checkout call failed: %s", e)
                res = {"outcome": "error", "decline_code": "api_error"}
        else:
            res = {"outcome": j.payment_outcome, "decline_code": j.decline_code}
            await db.execute(
                """INSERT INTO acme.payment_attempts (id, user_id, created_at, amount_cents, provider, outcome,
                       decline_code, card_country, card_brand, synthetic)
                   VALUES (%s,%s,%s,1200,'mock',%s,%s,%s,'visa',true) ON CONFLICT DO NOTHING""",
                (
                    f"pa_{j.session_id[-16:]}",
                    user_id,
                    j.events[-1].ts,
                    j.payment_outcome,
                    j.decline_code,
                    j.country,
                ),
            )
        last = j.events[-1]
        if res.get("outcome") == "succeeded":
            last.name, last.props = "payment_succeeded", {"plan": "pro", "amount_cents": 1200}
            stats["paid"] += 1
        else:
            last.name, last.props = "payment_failed", {"decline_code": res.get("decline_code") or "error"}
            stats["declined" if res.get("outcome") == "declined" else "errors"] += 1
        j.payment_outcome = res.get("outcome")
    return stats


# ------------------------------------------------------------------------------------------- the tick


async def tick(now: datetime | None = None, *, skip_browsers: bool = False) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    schedule = load_schedule()
    await ads.seed_campaigns()
    await create_project("acme", "Acme Notes", env("WHYDUNIT_INGEST_KEY"))

    start = await state.get_time("start")
    if start is None:
        start = now
        await state.put("start", start.isoformat())
        log.info("simulator start recorded: %s", start.isoformat())
    last_end = await state.get_time("last_tick_end")
    w_start = (
        max(last_end, now - schedule.max_tick_window)
        if last_end
        else now - timedelta(minutes=schedule.tick_minutes)
    )
    w_end = now
    if w_end <= w_start:
        return {"skipped": "empty window"}

    tick_row = await db.fetchrow(
        "INSERT INTO sim.ticks (window_start, window_end) VALUES (%s,%s) RETURNING id", (w_start, w_end)
    )
    summary: dict[str, Any] = {
        "window": [w_start.isoformat(), w_end.isoformat()],
        "t_plus_days": round((now - start).total_seconds() / 86400, 3),
    }
    acme = Acme()
    ingest = EngineIngest()
    seed = int(w_start.timestamp())
    rng = random.Random(seed)
    nprng = np.random.default_rng(seed)
    try:
        # 1. Incidents due by now.
        fired: dict[str, Any] = await state.get("incidents_fired", {})
        mitigations: dict[str, str] = await state.get("mitigations", {})
        for inc in schedule.incidents:
            if inc.id in fired or now < inc.starts(start):
                continue
            try:
                details = await fire_incident(inc, now)
                fired[inc.id] = {"at": now.isoformat(), "details": details}
                await state.put("incidents_fired", fired)
                summary.setdefault("fired", []).append(inc.id)
                log.warning("INCIDENT FIRED %s %s", inc.id, details)
            except Exception as e:  # noqa: BLE001 - retried next tick
                summary.setdefault("incident_errors", {})[inc.id] = f"{type(e).__name__}: {e}"[:300]
                log.error("incident %s failed: %s", inc.id, e)
        gt = await update_ground_truth(schedule, start, fired, mitigations)

        # 2. Production health per browser (real Playwright probes).
        health: dict[str, bool]
        if acme.available and not skip_browsers:
            from simulator.browser import probe_all

            deploy = await acme.health()
            results = await probe_all(acme.base_url)
            await state.record_health(results, deploy.get("deployment"))
            infra = [k for k, r in results.items() if r.get("infra")]
            known = await state.last_health()
            health = {k: (known.get(k, True) if k in infra else r["ok"]) for k, r in results.items()}
            summary["health"] = health
            summary["deployment"] = deploy
        else:
            health = await state.last_health() or {p: True for p in PROBES}
            summary["health"] = {"carried_over": health}

        # 3. Simulated ad platform for the window (same day-level demand noise as organic traffic).
        scale = float(schedule.traffic.get("scale", 1.0))  # turn the world down after the video is recorded
        model = WorldModel(
            organic_per_day=float(schedule.traffic.get("organic_per_day", 1900)) * scale, seed=seed
        )
        paid_clicks: list[tuple[datetime, str]] = []
        day_start = w_start.replace(hour=0, minute=0, second=0, microsecond=0)
        for c in await ads.campaigns():
            spent = await ads.spent_on_day(
                c.id, day_start, w_start.replace(minute=0, second=0, microsecond=0)
            )
            budget = ads.budget_fn(await ads.budget_timeline(c.id, day_start))
            hours = simulate(
                c,
                w_start,
                w_end,
                spent_before=spent,
                budget_at=budget,
                rng=nprng,
                demand_mult=lambda t: model.day_noise(t) * scale,
            )
            await ads.record_hours(hours)
            paid_clicks += [(t, c.name) for h in hours for t in h.click_times]
        summary["paid_clicks"] = len(paid_clicks)

        # 4. Visitors and their funnel journeys under current conditions.
        declines = payment_declines_active(schedule, start, fired, mitigations, now)
        cond = Conditions(
            signup_ok={p: health.get(p, True) for p in PROBES}, decline_rate_by_country=declines
        )
        journeys = model.journeys(
            w_start, w_end, paid_clicks=paid_clicks, conditions=lambda t: cond, rng=nprng
        )
        summary["visitors"] = len(journeys)
        summary["signup_blocked"] = sum(j.signup_blocked for j in journeys)
        summary["acme"] = await run_journeys(journeys, acme, rng)
        events = [e for j in journeys for e in journey_events(j, rng)]
        summary["events"] = await ingest.send(events)

        # 5. Support tickets and reviews (emergent from what visitors actually experienced).
        msgs = voice.plan_messages((w_start, w_end), journeys, schedule.voice, rng)
        await voice.write_text(msgs, rng)
        for m in msgs:
            meta = {
                "topic_hint": None,
                **{k: m.context.get(k) for k in ("device", "browser", "os", "country")},
            }
            if m.kind == "ticket":
                if acme.available:
                    await acme.contact(m.name, m.email, m.subject, m.body, meta)
                else:
                    await insert_ticket_direct(m.created_at, m.name, m.email, m.subject, m.body, meta)
            else:
                await insert_review(
                    m.created_at, m.platform or "app_store", m.rating or 3, m.subject, m.body, m.name
                )
        summary["tickets"] = sum(m.kind == "ticket" for m in msgs)
        summary["reviews"] = sum(m.kind == "review" for m in msgs)

        # 6. A few real recorded sessions in real browsers.
        if acme.available and not skip_browsers:
            from simulator.browser import real_sessions

            lo, hi = schedule.traffic.get("real_sessions_per_tick", [2, 4])
            countries = schedule.traffic.get("replay_country_mix", ["US", "GB", "BR"])
            summary["real_sessions"] = await real_sessions(
                acme.base_url, rng.randint(lo, hi), countries, rng, decline_for=declines
            )

        await state.put("last_tick_end", w_end.isoformat())
        await db.execute(
            "UPDATE sim.ticks SET finished_at = now(), ok = true, summary = %s WHERE id = %s",
            (db.jsonb(summary), tick_row["id"]),
        )
        summary["ground_truth"] = gt
        return summary
    except Exception as e:
        await db.execute(
            "UPDATE sim.ticks SET finished_at = now(), ok = false, summary = %s, error = %s WHERE id = %s",
            (db.jsonb(summary), f"{type(e).__name__}: {e}"[:1000], tick_row["id"]),
        )
        raise
    finally:
        await acme.close()
        await ingest.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-browsers", action="store_true")
    ap.add_argument("--now", help="ISO time to simulate up to (default: now)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    async def run() -> dict[str, Any]:
        try:
            now = datetime.fromisoformat(args.now) if args.now else None
            return await tick(now, skip_browsers=args.skip_browsers)
        finally:
            await db.close_pool()

    summary = asyncio.run(run())
    gt = summary.pop("ground_truth", None)
    if gt:
        GROUND_TRUTH_PATH.write_text(json.dumps(gt, indent=2) + "\n")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
