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
