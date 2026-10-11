"""HTTP API and dashboard for the SIMULATED ad platform.

The JSON API is shaped like Google Ads reporting (campaigns, budgets, metrics, change events). The
dashboard is plain server-rendered HTML; Stage 12's screen-reader reads it with the API switched off.
"""

from __future__ import annotations

import html
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from engine.mock_ads import store
from engine.settings import env

router = APIRouter(prefix="/mock-ads", tags=["mock-ads (simulated)"])
CUSTOMER_ID = "482-113-9050"
SIMULATED_NOTE = "SIMULATED ad platform for the Whydunit demo — not Google Ads."


def require_admin(x_admin_key: str | None) -> None:
    expected = env("WHYDUNIT_ADMIN_KEY")
    if expected and x_admin_key != expected:
        raise HTTPException(403, "admin key required")


async def require_api() -> None:
    if not await store.api_enabled():
        raise HTTPException(503, "API access is disabled for this account (no-API mode). Use the dashboard.")


def _parse_day(s: str | None, default: date) -> date:
    return date.fromisoformat(s) if s else default


@router.get("/api/campaigns")
async def list_campaigns() -> dict[str, Any]:
    await require_api()
    cs = await store.campaigns()
    return {
        "simulated": True,
        "customer_id": CUSTOMER_ID,
        "results": [
            {
                "campaign.id": c.id,
                "campaign.name": c.name,
                "campaign.status": c.status,
                "campaign_budget.amount_micros": int(c.daily_budget * store.MICROS),
            }
            for c in cs
        ],
    }


@router.get("/api/reports/campaign_daily")
async def campaign_daily(start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    await require_api()
    today = datetime.now(UTC).date()
    rows = await store.daily_report(
        _parse_day(start_date, today - timedelta(days=13)), _parse_day(end_date, today)
    )
    budgets = {c.id: int(c.daily_budget * store.MICROS) for c in await store.campaigns()}
    for r in rows:
        r["campaign_budget.amount_micros.current"] = budgets.get(r["campaign.id"])
    return {"simulated": True, "customer_id": CUSTOMER_ID, "results": rows}


@router.get("/api/reports/campaign_hourly")
async def campaign_hourly(start: datetime = Query(...), end: datetime = Query(...)) -> dict[str, Any]:
    await require_api()
    return {"simulated": True, "results": await store.hourly_report(start, end)}


@router.get("/api/change_events")
async def change_events(start: datetime | None = None, end: datetime | None = None) -> dict[str, Any]:
    await require_api()
    end = end or datetime.now(UTC)
    start = start or end - timedelta(days=14)
    return {"simulated": True, "customer_id": CUSTOMER_ID, "results": await store.change_events(start, end)}


class BudgetChange(BaseModel):
    amount: float = Field(gt=0, le=100_000)
    user_email: str = "whydunit-fix@acme-notes.test"
    client_type: str = "GOOGLE_ADS_API"


@router.post("/api/campaigns/{campaign_id}/budget")
async def change_budget(
    campaign_id: str, body: BudgetChange, x_admin_key: str | None = Header(default=None)
) -> dict[str, Any]:
    require_admin(x_admin_key)
    try:
        return {
            "simulated": True,
            **await store.set_budget(
                campaign_id, body.amount, user_email=body.user_email, client_type=body.client_type
            ),
        }
    except KeyError as e:
        raise HTTPException(404, "unknown campaign") from e


class ApiSwitch(BaseModel):
    enabled: bool


@router.post("/api/settings/api_access")
async def api_access(body: ApiSwitch, x_admin_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_key)
    await store.set_api_enabled(body.enabled)
    return {"api_enabled": body.enabled}


# --------------------------------------------------------------------------------------------- dashboard


def _bar_chart(days: list[str], series: dict[str, list[float]], budgets: dict[str, list[float]]) -> str:
    w, h, pad = 720, 220, 32
    n = max(len(days), 1)
    vmax = max(
        [max(v, default=0) for v in series.values()] + [max(v, default=0) for v in budgets.values()] + [1]
    )
    bw = (w - 2 * pad) / n
    colors = ["#2563eb", "#0d9488"]
    parts = [f'<svg viewBox="0 0 {w} {h + 40}" class="chart" role="img" aria-label="Daily cost by campaign">']
    for gi in range(5):
        y = pad + (h - pad) * gi / 4
        val = vmax * (1 - gi / 4)
        parts.append(
            f'<line x1="{pad}" x2="{w - pad}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{pad - 4}" y="{y + 4:.1f}" class="axis" text-anchor="end">${val:.0f}</text>'
        )
    for si, (name, vals) in enumerate(series.items()):
        sub = bw / (len(series) + 0.6)
        for i, v in enumerate(vals):
            x = pad + i * bw + sub * (si + 0.3)
            bh = (h - pad) * v / vmax
            parts.append(
                f'<rect x="{x:.1f}" y="{h - bh:.1f}" width="{sub * 0.9:.1f}" height="{bh:.1f}" '
                f'fill="{colors[si % 2]}"><title>{html.escape(name)} {days[i]}: ${v:.2f}</title></rect>'
            )
        bud = budgets.get(name, [])
        pts = " ".join(
            f"{pad + i * bw + bw / 2:.1f},{h - (h - pad) * b / vmax:.1f}" for i, b in enumerate(bud)
        )
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{colors[si % 2]}" stroke-dasharray="4 3"/>'
        )
    for i, d in enumerate(days):
        parts.append(
            f'<text x="{pad + i * bw + bw / 2:.1f}" y="{h + 16}" class="axis" text-anchor="middle">{d[5:]}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


@router.get("/", response_class=HTMLResponse)
async def dashboard(days: int = 10) -> str:
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    rows = await store.daily_report(start, today)
    camps = await store.campaigns()
    changes = await store.change_events(
        datetime.combine(start, datetime.min.time(), tzinfo=UTC), datetime.now(UTC) + timedelta(minutes=1)
    )
    day_list = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    cost = {c.name: [0.0] * days for c in camps}
    for r in rows:
        i = day_list.index(r["segments.date"])
        cost[r["campaign.name"]][i] = r["metrics.cost_micros"] / store.MICROS
    budgets: dict[str, list[float]] = {}
    for c in camps:
        tl = await store.budget_timeline(c.id, datetime.combine(start, datetime.min.time(), tzinfo=UTC))
        fn = store.budget_fn(tl)
        budgets[c.name] = [
            fn(datetime.combine(date.fromisoformat(d), datetime.max.time(), tzinfo=UTC)) for d in day_list
        ]

    def money(m: int) -> str:
        return f"${m / store.MICROS:,.2f}"

    table = "".join(
        f"<tr><td>{r['segments.date']}</td><td>{html.escape(r['campaign.name'])}</td>"
        f"<td class=num>{r['metrics.impressions']:,}</td><td class=num>{r['metrics.clicks']:,}</td>"
        f"<td class=num>{money(r['metrics.cost_micros'])}</td>"
        f"<td>{'<span class=pill>Limited by budget</span>' if r['campaign.primary_status_reasons'] else 'Eligible'}"
        f"{' from ' + str(r['metrics.first_budget_limited_hour']) + ':00' if r['metrics.first_budget_limited_hour'] is not None else ''}</td></tr>"
        for r in reversed(rows)
    )
    camp_rows = "".join(
        f"<tr><td>{c.id}</td><td>{html.escape(c.name)}</td><td>{c.status.title()}</td>"
        f"<td class=num>${c.daily_budget:,.2f}/day</td></tr>"
        for c in camps
    )
    change_rows = "".join(
        f"<tr><td>{e['change_event.change_date_time'][:16].replace('T', ' ')} UTC</td>"
        f"<td>{html.escape(e['campaign.name'])}</td><td>Budget</td>"
        f"<td class=num>{money(e['change_event.old_resource']['campaign_budget']['amount_micros'])} → "
        f"{money(e['change_event.new_resource']['campaign_budget']['amount_micros'])}</td>"
        f"<td>{html.escape(e['change_event.user_email'])}</td></tr>"
        for e in reversed(changes)
    ) or ("<tr><td colspan=5 class=muted>No changes in this period</td></tr>")
    legend = "".join(
        f'<span><i style="background:{c}"></i>{html.escape(n)}</span>'
        for n, c in zip(cost, ["#2563eb", "#0d9488"], strict=False)
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>AdPilot · Campaigns (simulated)</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#1f2328;--muted:#667085;--line:#e4e7ec;--accent:#2563eb}}
*{{box-sizing:border-box}}body{{margin:0;font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}}
.sim{{background:#fff4e5;color:#8a4b00;padding:8px 16px;font-weight:600;text-align:center;border-bottom:1px solid #f5d0a0}}
header{{display:flex;align-items:center;gap:12px;padding:14px 24px;background:var(--card);border-bottom:1px solid var(--line)}}
header b{{font-size:16px}}header .acct{{color:var(--muted)}}
main{{max-width:1080px;margin:0 auto;padding:20px 16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:16px}}
h2{{font-size:15px;margin:0 0 12px}}table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}}th{{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}.muted{{color:var(--muted)}}
.pill{{background:#fef3f2;color:#b42318;border-radius:999px;padding:2px 8px;font-size:12px;font-weight:600}}
.chart{{width:100%;height:auto}}.chart .grid{{stroke:var(--line)}}.chart .axis{{fill:var(--muted);font-size:11px}}
.legend{{display:flex;gap:16px;color:var(--muted);font-size:12px;margin-top:6px}}.legend i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}}
.scroll{{overflow-x:auto}}
</style></head><body>
<div class="sim">{SIMULATED_NOTE}</div>
<header><b>AdPilot</b><span class="acct">Acme Notes · Customer {CUSTOMER_ID}</span></header>
<main>
<section class="card"><h2>Cost per day vs daily budget (dashed)</h2>{_bar_chart(day_list, cost, budgets)}
<div class="legend">{legend}</div></section>
<section class="card scroll"><h2>Campaigns</h2><table><thead><tr><th>ID</th><th>Campaign</th><th>Status</th><th class=num>Budget</th></tr></thead><tbody>{camp_rows}</tbody></table></section>
<section class="card scroll"><h2>Daily performance</h2><table id="daily"><thead><tr><th>Date</th><th>Campaign</th><th class=num>Impr.</th><th class=num>Clicks</th><th class=num>Cost</th><th>Status</th></tr></thead><tbody>{table}</tbody></table></section>
<section class="card scroll"><h2>Change history</h2><table id="changes"><thead><tr><th>When</th><th>Campaign</th><th>Change</th><th class=num>Old → New</th><th>User</th></tr></thead><tbody>{change_rows}</tbody></table></section>
</main></body></html>"""
