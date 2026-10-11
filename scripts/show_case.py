"""Print a case's interrogation thread, judgements and verdict.  uv run python scripts/show_case.py [case_id]"""

import asyncio
import sys

from engine import db
from engine.runtime import events as ev


async def main(case_id: str | None) -> None:
    if not case_id:
        case_id = (await db.fetchrow("SELECT id FROM cases ORDER BY created_at DESC LIMIT 1"))["id"]
    print("case", case_id)
    for e in await ev.events_since(case_id, 0, 10000):
        p = e["payload"]
        if e["type"] == "question":
            print(f"Q → {p['question']['to']:9} {p['question']['text']}")
        elif e["type"] == "answer":
            print(f"   ← {p['answer']['verdict']:16} {p['answer']['text']}")
        elif e["type"] == "judgement":
            h = p["hypothesis"]
            print(f"⚖ {h['status']:12} {h['statement']}  ({h['reason']})")
        elif e["type"] == "verdict":
            v = p["verdict"]
            print(f"\nVERDICT [{v['kind']}]\n{v['narrative']}")
            for a in v["actions"]:
                print(f"  → {a['type']}: {a['title']}")
            if v["not_checked"]:
                print("  not checked:", "; ".join(v["not_checked"])[:300])
    await db.close_pool()


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
