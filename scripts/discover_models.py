"""List Token Factory models, pick the Nemotron IDs per role, and optionally pin them in config/models.yaml.

uv run python scripts/discover_models.py           # print
uv run python scripts/discover_models.py --write   # also rewrite the role ids
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

import yaml

from engine.runtime.llm import LLM, LLMUnavailable
from engine.settings import CONFIG_DIR

# Ordered preference patterns per role, matched against lowercase model ids.
PATTERNS = {
    "nano": [r"nemotron-3-nano-30b", r"nemotron-3-nano(?!.*omni)", r"nemotron.*nano(?!.*(omni|vl))"],
    "super": [r"nemotron-3-super", r"nemotron.*super"],
    "ultra": [r"nemotron-3-ultra", r"nemotron.*ultra"],
    "omni": [r"nemotron.*omni", r"nemotron.*nano.*vl", r"nemotron.*vl"],
}


def pick(ids: list[str]) -> dict[str, str | None]:
    lower = {i.lower(): i for i in ids}
    out: dict[str, str | None] = {}
    for role, pats in PATTERNS.items():
        out[role] = None
        for pat in pats:
            hits = sorted(orig for low, orig in lower.items() if re.search(pat, low))
            if hits:
                out[role] = hits[0]
                break
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    llm = LLM()
    try:
        models = await llm.backend.list_models()  # type: ignore[attr-defined]
    except LLMUnavailable as e:
        print(f"cannot list models: {e}", file=sys.stderr)
        return 2
    ids = sorted(m["id"] for m in models)
    nemotron = [i for i in ids if "nemotron" in i.lower()]
    print(f"{len(ids)} models served; {len(nemotron)} Nemotron:")
    for i in nemotron:
        print("  ", i)
    chosen = pick(ids)
    print("\nsuggested roles:")
    for role, mid in chosen.items():
        print(f"  {role:6} {mid or '— not found'}")
    if args.write:
        path = CONFIG_DIR / "models.yaml"
        text = path.read_text()
        cfg = yaml.safe_load(text)
        for role, mid in chosen.items():
            if not mid:
                continue
            old = cfg["roles"][role]["id"]
            text = re.sub(
                rf"(\n  {role}:\n    id: ){re.escape(old)}\n    verified: \w+",
                rf"\g<1>{mid}\n    verified: true",
                text,
            )
        path.write_text(text)
        print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
