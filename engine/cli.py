"""`uv run whydunit …` command line."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def _db_upgrade(args: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    from engine.settings import ROOT

    cfg = Config(str(ROOT / "alembic.ini"))
    command.upgrade(cfg, args.revision)
    print("database at", args.revision)
    return 0


def _project_create(args: argparse.Namespace) -> int:
    from engine import db
    from engine.projects import create_project

    async def run() -> str:
        try:
            return await create_project(args.id, args.name, args.key)
        finally:
            await db.close_pool()

    key = asyncio.run(run())
    print(f"project {args.id} ready; ingest key (shown once):\n{key}")
    return 0


def _world_create(args: argparse.Namespace) -> int:
    from datetime import date

    from engine.fixtures.world import WorldSpec, generate

    if args.preset:
        spec = WorldSpec.preset(args.preset)
    else:
        if not args.incidents:
            raise SystemExit("--incidents or --preset is required")
        spec = WorldSpec(
            name=args.name or "custom",
            start=date.fromisoformat(args.start),
            days=args.days,
            incidents=args.incidents,
            seed=args.seed,
        )
    res = generate(spec, ground_truth=not args.no_truth)
    print(f"world {spec.name} -> {res.path} in {res.seconds:.1f}s")
    for table, n in sorted(res.counts.items()):
        print(f"  {table:16} {n:>8,}")
    print(json.dumps({"case": res.meta["case"], "truth": res.meta["truth"]}, indent=2))
    return 0


def _case_open(args: argparse.Namespace) -> int:
    import logging

    from engine import db
    from engine.runtime import events as ev
    from engine.runtime.orchestrator import investigate

    logging.basicConfig(level=logging.WARNING)

    async def run() -> int:
        done = asyncio.Event()
        state: dict = {}

        async def printer() -> None:
            while "case" not in state:
                await asyncio.sleep(0.05)
            async for e in ev.stream(state["case"], follow=True, poll_s=0.2):
                if e.get("heartbeat"):
                    continue
                print(_fmt_event(e), flush=True)
                if e["type"] == "investigation_complete":
                    break
            done.set()

        async def runner() -> dict:
            from engine.runtime import orchestrator

            orig = orchestrator.open_case

            async def open_and_mark(*a, **k):
                case, reg = await orig(*a, **k)
                state["case"] = case.id
                return case, reg

            orchestrator.open_case = open_and_mark
            try:
                return await investigate(
                    args.world,
                    args.metric,
                    detectives=args.detectives.split(",") if args.detectives else None,
                    with_lead=not args.no_lead,
                )
            finally:
                orchestrator.open_case = orig

        try:
            p = asyncio.create_task(printer())
            res = await runner()
            await asyncio.wait_for(done.wait(), timeout=30)
            p.cancel()
            print(f"\ncase {res['case'].id} — stream: GET /cases/{res['case'].id}/stream")
            return 0
        finally:
            await db.close_pool()

    return asyncio.run(run())


def _fmt_event(e: dict) -> str:
    p, actor = e["payload"], e["actor"] or ""
    t = e["type"]
    if t == "evidence_pinned":
        x = p["evidence"]
        body = f"{x['id']} [{x['kind']} · {x['connector']} · tier {x['tier']}] {x['summary'][:110]}"
    elif t in ("finding", "finding_rejected"):
        f = p["finding"]
        body = f"({f['kind']}, conf {f['confidence']:.2f}) {f['claim']}" + (
            f"  ✗ {f.get('rejection_reason')}" if t == "finding_rejected" else ""
        )
    elif t == "tool_call":
        body = f"{p['tool']}({json.dumps(p.get('args'))[:90]})"
    elif t == "tool_result":
        body = f"{p['tool']} → {json.dumps(p.get('result'), default=str)[:110]}"
    elif t == "detective_report":
        r = p["report"]
        body = (
            f"report ({r['model_mode']}): {len(r['findings'])} findings, {len(r['suspicions'])} suspicions, "
            f"{len(r['cannot_determine'])} cannot-determine in {p.get('seconds')}s"
        )
    elif t == "case_opened":
        c = p["case"]
        body = (
            f"{c['question']} [{p['world_label']}] window {c['window_start'][:16]} → {c['window_end'][:16]}"
        )
    else:
        body = json.dumps(p, default=str)[:160]
    return f"{e['seq']:>4} {t:<22} {actor:<10} {body}"


def _watch(args: argparse.Namespace) -> int:
    import logging
    from datetime import datetime

    from engine import db
    from engine.runtime.watcher import watch_once

    logging.basicConfig(level=logging.INFO)

    async def run() -> dict:
        try:
            now = datetime.fromisoformat(args.now) if args.now else None
            return await watch_once(args.world, now, investigate=not args.dry_run)
        finally:
            await db.close_pool()

    print(json.dumps(asyncio.run(run()), indent=2, default=str))
    return 0


def _fix_approve(args: argparse.Namespace) -> int:
    from engine import db
    from engine.agents import fixer

    async def run() -> dict:
        try:
            return await fixer.approve(args.fix_id)
        finally:
            await db.close_pool()

    fix = asyncio.run(run())
    print(f"{fix['id']}: {fix['status']}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("engine.api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="whydunit")
    sub = p.add_subparsers(dest="cmd", required=True)

    dbp = sub.add_parser("db").add_subparsers(dest="db_cmd", required=True)
    up = dbp.add_parser("upgrade")
    up.add_argument("revision", nargs="?", default="head")
    up.set_defaults(func=_db_upgrade)

    pp = sub.add_parser("project").add_subparsers(dest="project_cmd", required=True)
    pc = pp.add_parser("create")
    pc.add_argument("id")
    pc.add_argument("name")
    pc.add_argument("--key", help="use this key instead of generating one")
    pc.set_defaults(func=_project_create)

    wp = sub.add_parser("world").add_subparsers(dest="world_cmd", required=True)
    wc = wp.add_parser("create", help="generate a fixture world into .cache/worlds/<name>.duckdb")
    wc.add_argument("--preset", help="named world from config/worlds.yaml, e.g. 3inc")
    wc.add_argument("--incidents", help="e.g. deploy_bug:webkit,ads_budget_cap,payment_declines:BR")
    wc.add_argument("--start", default="2026-09-14")
    wc.add_argument("--days", type=int, default=14)
    wc.add_argument("--name")
    wc.add_argument("--seed", type=int, default=7)
    wc.add_argument("--no-truth", action="store_true", help="skip the counterfactual ground-truth worlds")
    wc.set_defaults(func=_world_create)

    cp = sub.add_parser("case").add_subparsers(dest="case_cmd", required=True)
    co = cp.add_parser("open", help="open and investigate a case")
    co.add_argument("--world", default="fixture:3inc", help="live or fixture:<preset>")
    co.add_argument("--metric", default="paid_subs")
    co.add_argument("--detectives", help="comma-separated subset, e.g. funnel")
    co.add_argument("--no-lead", action="store_true")
    co.set_defaults(func=_case_open)

    wa = sub.add_parser("watch", help="one watcher pass: verify open cases, open a case on a sustained drop")
    wa.add_argument("--world", default="live")
    wa.add_argument("--now", help="ISO time to evaluate at")
    wa.add_argument("--dry-run", action="store_true", help="detect only; don't open a case")
    wa.set_defaults(func=_watch)

    fp = sub.add_parser("fix").add_subparsers(dest="fix_cmd", required=True)
    fa = fp.add_parser("approve", help="apply an approval-gated fix (merge PR / restore budget / mitigation)")
    fa.add_argument("fix_id")
    fa.set_defaults(func=_fix_approve)

    sp = sub.add_parser("serve")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--reload", action="store_true")
    sp.set_defaults(func=_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
