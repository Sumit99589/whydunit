"""python -m runner run-flows --spec spec.json | render-replay --spec spec.json | serve [--port 8080]

The spec may also come from the RUNNER_SPEC environment variable (JSON), which is how a Nebius Serverless
Job or a GitHub Actions dispatch passes it in.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(prog="runner")
    ap.add_argument("command", choices=["run-flows", "render-replay", "capture", "serve"])
    ap.add_argument("--spec", help="path to a JSON spec (default: $RUNNER_SPEC)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "serve":
        import uvicorn

        uvicorn.run("runner.server:app", host="0.0.0.0", port=args.port)
        return 0
    raw = Path(args.spec).read_text() if args.spec else os.environ.get("RUNNER_SPEC")
    if not raw:
        print("no spec: pass --spec or set RUNNER_SPEC", file=sys.stderr)
        return 2
    spec = json.loads(raw)
    from runner import jobs

    fn = {"run-flows": jobs.run_flows, "render-replay": jobs.render_replays, "capture": jobs.capture_pages}[
        args.command
    ]
    out = asyncio.run(fn(spec))
    print(json.dumps({k: v for k, v in out.items() if k not in ("results", "recordings")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
