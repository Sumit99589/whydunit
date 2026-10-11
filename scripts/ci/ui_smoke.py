"""UI smoke test + screenshots (Stage 10 "done when"). Runs in CI against `next start` + the engine.

uv run python scripts/ci/ui_smoke.py http://127.0.0.1:3000 ui-shots
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3000"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "ui-shots")
failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


async def no_overflow(page, label: str) -> None:
    sw = await page.evaluate("document.scrollingElement.scrollWidth")
    vw = await page.evaluate("window.innerWidth")
    check(sw <= vw + 1, f"{label}: no horizontal scroll ({sw} <= {vw})")


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for theme in ("light", "dark"):
            for name, vp in (
                ("desktop", {"width": 1440, "height": 900}),
                ("mobile", {"width": 390, "height": 844}),
            ):
                ctx = await browser.new_context(viewport=vp, color_scheme=theme)
                page = await ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e, errs=errors: errs.append(str(e)))
                page.on("console", lambda m, errs=errors: errs.append(m.text) if m.type == "error" else None)
                await page.goto(f"{BASE}/", wait_until="networkidle")
                check(
                    await page.get_by_role("heading", name="Know why your numbers dropped.").is_visible(),
                    f"{theme}/{name}: landing renders",
                )
                await page.wait_for_timeout(16500 if name == "desktop" and theme == "light" else 300)
                await page.screenshot(path=OUT / f"landing-{name}-{theme}.png", full_page=True)
                await no_overflow(page, f"{theme}/{name} landing")
                await page.goto(f"{BASE}/cases/flagship", wait_until="domcontentloaded")
                await page.get_by_text("Three causes explain it").wait_for(timeout=30000)
                await page.wait_for_timeout(3500)  # let the waterfall draw in
                check(
                    await page.locator("text=Interrogation").first.is_visible(),
                    f"{theme}/{name}: board shows the interrogation",
                )
                check(
                    await page.get_by_role("heading", name="Evidence wall").is_visible(),
                    f"{theme}/{name}: board shows the evidence wall",
                )
                await page.screenshot(path=OUT / f"case-{name}-{theme}.png", full_page=True)
                await page.screenshot(path=OUT / f"case-{name}-{theme}-fold.png")
                await no_overflow(page, f"{theme}/{name} case board")
                bad = [e for e in errors if "favicon" not in e]
                check(not bad, f"{theme}/{name}: no console errors {bad[:2]}")
                await ctx.close()

        # Replay mode and the playground, desktop light.
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        await page.goto(f"{BASE}/cases/flagship?replay=16", wait_until="domcontentloaded")
        await page.get_by_text("Replaying at").wait_for(timeout=15000)
        await page.wait_for_timeout(2500)
        await page.screenshot(path=OUT / "case-replay-midway.png")
        await page.get_by_text("Three causes explain it").wait_for(timeout=90000)
        check(True, "replay reaches the verdict")
        await page.goto(f"{BASE}/playground", wait_until="networkidle")
        await page.screenshot(path=OUT / "playground.png", full_page=True)
        await page.get_by_role("button", name="A deploy breaks signup on Safari").click()
        await page.wait_for_url("**/cases/case_*", timeout=20000)
        await page.wait_for_timeout(1500)
        await page.screenshot(path=OUT / "playground-case-live.png")
        await page.get_by_text("The cause is").wait_for(timeout=90000)
        check(True, "a playground case runs live to a verdict")
        await page.screenshot(path=OUT / "playground-case-verdict.png", full_page=True)
        await page.goto(f"{BASE}/cases", wait_until="networkidle")
        await page.screenshot(path=OUT / "cases.png")
        await page.goto(f"{BASE}/connect", wait_until="networkidle")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=OUT / "connect.png", full_page=True)
        await browser.close()
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
