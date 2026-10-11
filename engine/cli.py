"""`uv run whydunit …` command line."""

from __future__ import annotations

import argparse
import asyncio
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
