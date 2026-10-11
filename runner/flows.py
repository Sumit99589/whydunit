"""User flows run against a deployment URL in each browser of the matrix."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

from playwright.async_api import Browser, Page, Playwright
from playwright.async_api import TimeoutError as PWTimeout

# probe name -> (browser type, Playwright device descriptor or None for desktop)
MATRIX: dict[str, tuple[str, str | None]] = {
    "chromium-desktop": ("chromium", None),
    "webkit-desktop": ("webkit", None),
    "webkit-mobile": ("webkit", "iPhone 15"),
    "chromium-mobile": ("chromium", "Pixel 7"),
    "firefox-desktop": ("firefox", None),
}


async def new_context(p: Playwright, browsers: dict[str, Browser], probe: str, **launch: Any):
    kind, device = MATRIX[probe]
    if kind not in browsers:
        browsers[kind] = await getattr(p, kind).launch(**launch)
    opts: dict[str, Any] = dict(p.devices[device]) if device else {"viewport": {"width": 1440, "height": 900}}
    return await browsers[kind].new_context(**opts)


async def fill_signup(page: Page, name: str, email: str, *, delay: float = 0) -> None:
    await page.get_by_label("Your name").click()
    await page.get_by_label("Your name").press_sequentially(name, delay=delay)
    await page.get_by_label("Work email").press_sequentially(email, delay=delay)
    await page.get_by_label("Password").press_sequentially("correct-horse-battery", delay=delay)


async def signup_flow(page: Page, base_url: str, *, tag: str) -> dict[str, Any]:
    """New visitor signs up. Pass = reaching /onboarding within 10 s of clicking Create account."""
    errors: list[str] = []
    requests: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
    page.on("request", lambda r: requests.append(r.url) if "/api/signup" in r.url else None)
    t0 = time.monotonic()
    q = urlencode({"wd_disable": "1", "wd_synthetic": "1"})
    await page.goto(f"{base_url.rstrip('/')}/signup?{q}", wait_until="networkidle", timeout=30000)
    await fill_signup(page, "Runner Check", f"runner+{tag}-{int(time.time() * 1000)}@acme-notes.test")
    button = page.get_by_role("button", name="Create account")
    box = await button.bounding_box()
    # Is anything covering the button? (e.g. a sticky banner intercepting pointer events)
    covered = (
        await page.evaluate(
            "([x, y]) => { const el = document.elementFromPoint(x, y); "
            "return el ? (el.closest('button') ? null : (el.className || el.tagName).toString().slice(0, 80)) : null }",
            [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
        )
        if box
        else None
    )
    await button.click()
    try:
        await page.wait_for_url("**/onboarding", timeout=10000)
        return {"ok": True, "ms": int((time.monotonic() - t0) * 1000), "errors": errors}
    except PWTimeout:
        return {
            "ok": False,
            "ms": int((time.monotonic() - t0) * 1000),
            "url": page.url,
            "errors": errors,
            "error": "Timeout 10000ms waiting for navigation to /onboarding after clicking 'Create account'"
            + ("; no request to /api/signup was sent" if not requests else "; /api/signup was called"),
            "signup_request_sent": bool(requests),
            "button_covered_by": covered,
        }


FLOWS = {"signup": signup_flow}
