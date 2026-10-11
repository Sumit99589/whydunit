"""Print which engine-specific web APIs exist in Playwright's Chromium, WebKit and Firefox builds.

Used to pick a realistic WebKit-only bug for the planted incident (PLAN Stage 3). Runs in CI.
"""

import asyncio
import json

from playwright.async_api import async_playwright

CHECKS = {
    "requestIdleCallback": "typeof window.requestIdleCallback",
    "scheduler.postTask": "typeof (window.scheduler && window.scheduler.postTask)",
    "navigator.userAgentData": "typeof navigator.userAgentData",
    "css -webkit-touch-callout": "String(CSS.supports('-webkit-touch-callout', 'none'))",
    "Intl.Segmenter": "typeof Intl.Segmenter",
    "Array.fromAsync": "typeof Array.fromAsync",
}


async def main() -> None:
    async with async_playwright() as p:
        matrix = [
            ("chromium", None),
            ("webkit", None),
            ("webkit", "iPhone 15"),
            ("chromium", "Pixel 7"),
            ("firefox", None),
        ]
        for name, device in matrix:
            browser = await getattr(p, name).launch()
            ctx = await browser.new_context(**(p.devices[device] if device else {}))
            page = await ctx.new_page()
            await page.set_content("<html><body>probe</body></html>")
            out = {k: await page.evaluate(expr) for k, expr in CHECKS.items()}
            out["version"] = browser.version
            print(f"{name:9} {device or 'desktop':10} {json.dumps(out)}")
            await browser.close()


asyncio.run(main())
