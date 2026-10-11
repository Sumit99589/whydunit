"""Render rrweb recordings into keyframe PNGs with rrweb's Replayer inside a headless browser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.async_api import Browser

RRWEB_VERSION = "2.1.7"
STATIC = Path(__file__).parent / "static"
CDN = f"https://cdn.jsdelivr.net/npm/rrweb@{RRWEB_VERSION}/dist"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>{css}
html,body{{margin:0;background:#fff}} .replayer-wrapper{{transform-origin:0 0}}
#stage{{position:relative;overflow:hidden}} .replayer-mouse{{width:22px;height:22px;border-radius:50%;
background:rgba(232,89,12,.55);border:2px solid #e8590c;margin:-11px 0 0 -11px}}
.replayer-mouse.active{{background:rgba(232,89,12,.95)}}</style></head>
<body><div id="stage"></div><script>{js}</script></body></html>"""


def _asset(name: str) -> str | None:
    p = STATIC / name
    return p.read_text() if p.exists() else None


async def render(
    browser: Browser, events: list[dict[str, Any]], times_ms: list[int], *, width: int = 0, height: int = 0
) -> list[bytes]:
    """PNG for each absolute timestamp in `times_ms` (clamped to the recording)."""
    meta = next((e for e in events if e.get("type") == 4), {"data": {"width": 1280, "height": 800}})
    w, h = width or meta["data"].get("width", 1280), height or meta["data"].get("height", 800)
    ctx = await browser.new_context(viewport={"width": w, "height": h})
    page = await ctx.new_page()
    js, css = _asset("rrweb.umd.min.cjs"), _asset("style.min.css")
    if js and css:
        await page.set_content(PAGE.format(css=css, js=js))
    else:
        await page.set_content(PAGE.format(css="", js=""))
        await page.add_style_tag(url=f"{CDN}/style.min.css")
        await page.add_script_tag(url=f"{CDN}/rrweb.umd.min.cjs")
    await page.evaluate(
        """(events) => { window.__r = new rrweb.Replayer(events, {root: document.getElementById('stage'),
             skipInactive: false, mouseTail: false, triggerFocus: false, UNSAFE_replayCanvas: false});
             window.__start = events[0].timestamp; }""",
        events,
    )
    start = events[0]["timestamp"]
    shots = []
    for t in times_ms:
        offset = max(0, min(t, events[-1]["timestamp"]) - start)
        await page.evaluate("(o) => window.__r.pause(o)", offset)
        await page.wait_for_timeout(120)
        shots.append(await page.locator("#stage").screenshot(type="png"))
    await ctx.close()
    return shots


def load_events(src: str | Path) -> list[dict[str, Any]]:
    return json.loads(Path(src).read_text())
