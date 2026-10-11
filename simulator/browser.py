"""Real browsers against production Acme: health probes across the matrix, and recorded user sessions.

Runs in GitHub Actions (never fanned out locally; see PLAN A7.6).
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any
from urllib.parse import urlencode

from playwright.async_api import Browser, Page, Playwright, async_playwright
from playwright.async_api import TimeoutError as PWTimeout

log = logging.getLogger("whydunit.sim.browser")

# probe name -> (browser type, Playwright device descriptor or None for desktop)
PROBE_MATRIX: dict[str, tuple[str, str | None]] = {
    "chromium-desktop": ("chromium", None),
    "webkit-desktop": ("webkit", None),
    "webkit-mobile": ("webkit", "iPhone 15"),
    "chromium-mobile": ("chromium", "Pixel 7"),
    "firefox-desktop": ("firefox", None),
}

# Session personas: (probe, weight). iPhone-heavy so failures show up in recordings when they happen.
SESSION_MIX = [
    ("webkit-mobile", 0.35),
    ("chromium-desktop", 0.3),
    ("chromium-mobile", 0.2),
    ("webkit-desktop", 0.15),
]


async def _context(p: Playwright, browsers: dict[str, Browser], probe: str):
    kind, device = PROBE_MATRIX[probe]
    if kind not in browsers:
        browsers[kind] = await getattr(p, kind).launch()
    opts: dict[str, Any] = dict(p.devices[device]) if device else {"viewport": {"width": 1440, "height": 900}}
    return await browsers[kind].new_context(**opts)


async def _fill_signup(page: Page, name: str, email: str, rng: random.Random, human: bool) -> None:
    delay = (lambda: rng.uniform(40, 120)) if human else (lambda: 0)
    await page.get_by_label("Your name").click()
    await page.get_by_label("Your name").press_sequentially(name, delay=delay())
    await page.get_by_label("Work email").press_sequentially(email, delay=delay())
    await page.get_by_label("Password").press_sequentially("correct-horse-battery", delay=delay())


async def probe_signup(
    base_url: str, probe: str, p: Playwright, browsers: dict[str, Browser]
) -> dict[str, Any]:
    """Can a new visitor sign up on this browser? Success = reaching /onboarding within 10 s of submitting."""
    ctx = await _context(p, browsers, probe)
    page = await ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
    t0 = time.monotonic()
    try:
        q = urlencode({"wd_disable": "1", "wd_synthetic": "1"})
        await page.goto(f"{base_url}/signup?{q}", wait_until="networkidle", timeout=30000)
        stamp = int(time.time() * 1000)
        await _fill_signup(
            page, "Probe Bot", f"probe+{probe}-{stamp}@acme-notes.test", random.Random(), False
        )
        await page.get_by_role("button", name="Create account").click()
        await page.wait_for_url("**/onboarding", timeout=10000)
        return {"ok": True, "ms": int((time.monotonic() - t0) * 1000), "errors": errors}
    except PWTimeout as e:
        return {
            "ok": False,
            "ms": int((time.monotonic() - t0) * 1000),
            "error": str(e).splitlines()[0][:200],
            "url": page.url,
            "errors": errors,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "errors": errors, "infra": True}
    finally:
        await ctx.close()


async def probe_all(base_url: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    async with async_playwright() as p:
        browsers: dict[str, Browser] = {}
        try:
            for probe in PROBE_MATRIX:
                out[probe] = await probe_signup(base_url, probe, p, browsers)
                log.info("probe %s -> %s", probe, out[probe])
        finally:
            for b in browsers.values():
                await b.close()
    return out


async def real_session(
    base_url: str,
    probe: str,
    country: str,
    rng: random.Random,
    p: Playwright,
    browsers: dict[str, Browser],
    *,
    decline_pm: str | None = None,
) -> dict[str, Any]:
    """A human-paced visit with the snippet active and rrweb recording forced on."""
    ctx = await _context(p, browsers, probe)
    page = await ctx.new_page()
    result: dict[str, Any] = {"probe": probe, "country": country, "steps": []}
    params = {"wd_synthetic": "1", "wd_replay": "1", "wd_country": country}
    if rng.random() < 0.35:
        params.update(utm_source="google", utm_medium="cpc", utm_campaign="Search · Generic")
    try:
        await page.goto(f"{base_url}/?{urlencode(params)}", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(rng.uniform(1500, 4000))
        await page.mouse.wheel(0, rng.uniform(300, 900))
        await page.wait_for_timeout(rng.uniform(800, 2500))
        if await page.get_by_role("button", name="Accept").is_visible():
            await page.get_by_role("button", name="Accept").click()
        if rng.random() < 0.4:
            await page.get_by_role("link", name="Pricing").first.click()
            await page.wait_for_timeout(rng.uniform(2000, 5000))
            result["steps"].append("pricing")
        await page.get_by_role("link", name="Sign up").first.click()
        await page.wait_for_url("**/signup", timeout=15000)
        await page.wait_for_timeout(rng.uniform(800, 2000))
        first, last = (
            rng.choice(["Maya", "Lucas", "Ana", "Tom", "Priya"]),
            rng.choice(["Silva", "Patel", "Weber"]),
        )
        await _fill_signup(
            page,
            f"{first} {last}",
            f"{first.lower()}.{last.lower()}{rng.randint(10, 9999)}@example.com",
            rng,
            True,
        )
        button = page.get_by_role("button", name="Create account")
        await button.click()
        result["steps"].append("submit")
        try:
            await page.wait_for_url("**/onboarding", timeout=6000)
        except PWTimeout:
            # Nothing happened: a real person taps again, harder, then gives up.
            taps = rng.randint(3, 6)
            for _ in range(taps):
                await button.click(delay=rng.uniform(30, 90))
                await page.wait_for_timeout(rng.uniform(150, 450))
            result["steps"].append(f"rage_tap x{taps}")
            try:
                await page.wait_for_url("**/onboarding", timeout=3000)
            except PWTimeout:
                await page.wait_for_timeout(rng.uniform(1500, 3000))
                result["outcome"] = "signup_blocked"
                return result
        result["steps"].append("onboarding")
        await page.wait_for_timeout(rng.uniform(2000, 5000))
        if rng.random() < 0.6:
            await page.get_by_test_id("go-checkout").click()
            await page.wait_for_url("**/checkout", timeout=15000)
            await page.wait_for_timeout(rng.uniform(1500, 4000))
            pm = decline_pm or "pm_card_visa"
            await page.goto(f"{page.url.split('?')[0]}?pm={pm}", wait_until="networkidle")
            await page.get_by_role("button", name="Pay $12.00 and upgrade").click()
            await (
                page.get_by_test_id("checkout-success")
                .or_(page.get_by_test_id("checkout-error"))
                .wait_for(timeout=30000)
            )
            result["outcome"] = (
                "paid" if await page.get_by_test_id("checkout-success").is_visible() else "declined"
            )
        else:
            result["outcome"] = "signed_up"
        return result
    except Exception as e:  # noqa: BLE001
        result["outcome"] = "error"
        result["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
        return result
    finally:
        # Let the snippet flush its last batch and replay chunk.
        try:
            await page.wait_for_timeout(5500)
            await page.evaluate("window.whydunit && window.whydunit.flush(true)")
            await page.wait_for_timeout(1000)
        except Exception:  # noqa: BLE001
            pass
        await ctx.close()


async def real_sessions(
    base_url: str,
    n: int,
    countries: list[str],
    rng: random.Random,
    decline_for: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    out = []
    async with async_playwright() as p:
        browsers: dict[str, Browser] = {}
        try:
            for _ in range(n):
                probe = _weighted(rng, SESSION_MIX)
                country = rng.choice(countries)
                pm = None
                if decline_for and rng.random() < decline_for.get(country, 0.0):
                    pm = rng.choice(["pm_card_chargeDeclined", "pm_card_chargeDeclinedInsufficientFunds"])
                out.append(await real_session(base_url, probe, country, rng, p, browsers, decline_pm=pm))
                log.info("session -> %s", out[-1])
        finally:
            for b in browsers.values():
                await b.close()
    return out


def _weighted(rng: random.Random, items: list[tuple[str, float]]) -> str:
    x, acc = rng.random() * sum(w for _, w in items), 0.0
    for name, w in items:
        acc += w
        if x <= acc:
            return name
    return items[-1][0]
