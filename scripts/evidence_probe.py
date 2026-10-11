"""Print one evidence bundle per kind (Stage 5 "done when").

uv run python scripts/evidence_probe.py live           # the live Acme world
uv run python scripts/evidence_probe.py fixture:3inc   # a fixture world
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from engine import db
from engine.connectors import NoSource, registry_for
from engine.connectors.base import KINDS, Window

QUERIES = {"world_news": {"query": "Acme Notes outage OR team notes app launch"}}


async def main(world: str) -> int:
    reg = registry_for(world)
    if reg.mode == "fixture":
        from engine.connectors.fixture import FixtureWorld

        case = await reg.connectors[0].case_spec()  # type: ignore[union-attr]
        assert isinstance(reg.connectors[0], FixtureWorld)
        w = Window(datetime.fromisoformat(case["baseline_start"]), datetime.fromisoformat(case["window_end"]))
    else:
        now = datetime.now(UTC)
        w = Window(now - timedelta(days=7), now)
    print(f"{reg.label}: {w.start:%Y-%m-%d} → {w.end:%Y-%m-%d}\n")
    missing = 0
    for kind in KINDS:
        try:
            b = await reg.fetch(kind, w, QUERIES.get(kind, {}))
            print(f"[{kind:17}] {b.connector} (tier {b.tier}: {b.tier_label}) {b.id}\n    {b.summary}")
            if b.sample:
                print(f"    e.g. {dict(list(b.sample[0].items())[:6])}")
            for n in b.notes:
                print(f"    note: {n}")
        except NoSource as e:
            missing += 1
            print(f"[{kind:17}] CANNOT DETERMINE — {e}")
        except Exception as e:  # noqa: BLE001
            missing += 1
            print(f"[{kind:17}] ERROR {type(e).__name__}: {e}")
    await db.close_pool()
    print(f"\n{len(KINDS) - missing}/{len(KINDS)} kinds supplied")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "fixture:3inc")))
