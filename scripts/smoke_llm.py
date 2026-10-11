"""Stage 1 smoke test: one real call per Nemotron role, with latency, tokens and cost.

uv run python scripts/smoke_llm.py [--no-cache]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys

from PIL import Image, ImageDraw

from engine.runtime.cache import DiskCache
from engine.runtime.llm import LLM, CostMeter, LLMUnavailable

DUMMY_TOOL = {
    "type": "function",
    "function": {
        "name": "get_metric",
        "description": "Fetch a daily metric value for a date.",
        "parameters": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "enum": ["visitors", "signups", "paid_subs"]},
                "date": {"type": "string", "description": "ISO date"},
            },
            "required": ["metric", "date"],
        },
    },
}


def test_png() -> bytes:
    img = Image.new("RGB", (480, 280), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([140, 170, 340, 220], fill=(37, 99, 235))
    d.text((205, 188), "Sign up", fill="white")
    d.rectangle([0, 230, 480, 280], fill=(30, 30, 30))
    d.text((12, 248), "We use cookies. Accept", fill="white")
    d.text((140, 60), "Create your Acme Notes account", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    llm = LLM(cache=DiskCache(enabled=not args.no_cache))
    if not llm.available():
        print("NEBIUS_API_KEY not set: see BLOCKERS.md", file=sys.stderr)
        return 2
    meter = CostMeter()
    failures = 0

    async def run(label: str, coro):
        nonlocal failures
        try:
            r = await coro
            ok, detail = r
        except LLMUnavailable as e:
            ok, detail, r = False, str(e), None
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        last = meter.calls[-1] if meter.calls else None
        stats = (
            (
                f"{last.latency_s:5.1f}s {last.prompt_tokens:>5}+{last.completion_tokens:<5} tok "
                f"${last.cost_usd:.5f}{' (cached)' if last.cached else ''}"
            )
            if last
            else ""
        )
        print(f"[{'PASS' if ok else 'FAIL'}] {label:18} {stats}  {detail}")
        if not ok:
            failures += 1

    async def text(role):
        r = await llm.chat(
            role,
            [{"role": "user", "content": "Reply with exactly: OK whydunit"}],
            reasoning=False,
            max_tokens=256,
            meter=meter,
            tag=f"smoke:{role}",
        )
        return ("whydunit" in r.content.lower(), f"{r.model} -> {r.content.strip()[:60]!r}")

    async def tool():
        r = await llm.chat(
            "nano",
            [
                {"role": "system", "content": "You call tools to answer. Do not answer directly."},
                {"role": "user", "content": "How many paid subscriptions were there on 2026-10-06?"},
            ],
            tools=[DUMMY_TOOL],
            tool_choice="auto",
            reasoning=False,
            meter=meter,
            tag="smoke:tool",
        )
        if not r.tool_calls:
            return (False, f"no tool call; content={r.content[:80]!r}")
        tc = r.tool_calls[0]
        ok = tc.name == "get_metric" and tc.arguments.get("metric") == "paid_subs" and "date" in tc.arguments
        return (ok, f"{tc.name}({tc.raw_arguments})")

    async def vision():
        r = await llm.describe_images(
            "List the visible UI elements on this screenshot in one sentence. Mention any button text.",
            [test_png()],
            meter=meter,
            tag="smoke:omni",
        )
        return ("sign" in r.content.lower(), f"{r.model} -> {r.content.strip()[:100]!r}")

    for role in ("nano", "super", "ultra"):
        await run(f"text:{role}", text(role))
    await run("tool:nano", tool())
    await run("vision:omni", vision())
    print(f"\ntotal: {meter.summary()}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
