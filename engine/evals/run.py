"""The evaluation harness: ten planted scenarios with known answers, scored in one command.

    uv run whydunit evals run            # all scenarios → engine/evals/results.json + a markdown table
    uv run whydunit evals run --only S4

Everything is deterministic: fixture worlds (no network; their news corpus stands in for Tavily), the LLM response
cache on, and fixed seeds. A cause "matches" a planted incident when it names the same funnel factor and segment.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine import db
from engine.fixtures.world import load_meta, resolve_world
from engine.runtime.llm import get_llm
from engine.runtime.orchestrator import investigate

RESULTS = Path(__file__).parent / "results.json"


@dataclass
class Scenario:
    id: str
    world: str
    title: str
    expect: str  # causes | no_real_drop | measurement
    metric: str = "paid_subs"


SCENARIOS = [
    Scenario("S1", "deploy_only", "Deploy bug only (Safari signup)", "causes"),
    Scenario("S2", "ads_only", "Ads budget cap only", "causes"),
    Scenario("S3", "payments_only", "Payment declines only (Brazil)", "causes"),
    Scenario("S4", "3inc", "The flagship: all three causes", "causes"),
    Scenario("S5", "holiday_red_herring", "Public holiday, with a harmless deploy the same day", "causes"),
    Scenario("S6", "noise", "Noise only: no real drop", "no_real_drop"),
    Scenario("S7", "outage", "Payments provider outage on a status page", "causes"),
    Scenario("S8", "competitor", "Competitor launch found in the news", "causes"),
    Scenario("S9", "tracking", "Tracking bug: a measurement problem", "measurement", metric="signups"),
    Scenario("S10", "seasonality_small_bug", "Weekend dip plus a small Firefox bug", "causes"),
]


def _matches(cause: dict[str, Any], affects: dict[str, Any]) -> bool:
    if not affects or cause["factor"] != affects.get("factor"):
        return False
    seg_t, seg_c = affects.get("segment") or {}, cause.get("segment") or {}
    if not seg_t:
        return True  # a global incident matches any segment the detectives narrowed it to
    return all(
        seg_c.get(k) == v or (isinstance(seg_c.get(k), list) and v in seg_c[k]) for k, v in seg_t.items()
    )


def score(sc: Scenario, meta: dict[str, Any], verdict: dict[str, Any] | None) -> dict[str, Any]:
    truth_inc = [i for i in meta["incidents"] if i["causal"] and not i["affects"].get("measurement_only")]
    truth_shares = (meta.get("truth") or {}).get("incidents", {})
    kind = verdict["kind"] if verdict else "none"
    causes = verdict["causes"] if verdict else []
    matched, false_acc = [], []
    for c in causes:
        hit = next((i for i in truth_inc if _matches(c, i["affects"])), None)
        (matched if hit else false_acc).append((c, hit))
    errors = []
    for c, hit in matched:
        # A share is only defined when the incident really cost something (≥ 3 paid subscriptions).
        if hit["id"] in truth_shares and truth_shares[hit["id"]]["lost_paid_subs"] >= 3:
            errors.append(abs(c["share_of_explained"] - truth_shares[hit["id"]]["share"]) * 100)
    true_top = max(truth_inc, key=lambda i: truth_shares.get(i["id"], {}).get("share", 0), default=None)
    top = max(causes, key=lambda c: c["share"], default=None)
    if sc.expect == "causes":
        top_ok = bool(top and true_top and _matches(top, true_top["affects"]))
    else:
        top_ok = kind == sc.expect
    missed = [i["id"] for i in truth_inc if not any(_matches(c, i["affects"]) for c, _ in matched)]
    return {
        "verdict_kind": kind,
        "expected_kind": sc.expect,
        "kind_ok": kind == sc.expect,
        "top_cause_ok": top_ok,
        "causes": [
            {
                "statement": c["statement"],
                "share_of_explained": round(c["share_of_explained"], 4),
                "matched": hit["id"] if hit else None,
            }
            for c, hit in matched + false_acc
        ],
        "false_accusations": [c["statement"] for c, _ in false_acc],
        "missed": missed,
        "share_abs_errors_pp": [round(e, 2) for e in errors],
        "truth": {k: round(v["share"], 4) for k, v in truth_shares.items()},
    }


async def run_all(only: list[str] | None = None) -> dict[str, Any]:
    llm = get_llm()
    rows = []
    for sc in SCENARIOS:
        if only and sc.id not in only:
            continue
        path = resolve_world(f"fixture:{sc.world}")
        meta = load_meta(path)
        t0 = time.monotonic()
        res = await investigate(f"fixture:{sc.world}", sc.metric)
        secs = time.monotonic() - t0
        s = score(sc, meta, res["verdict"])
        rows.append(
            {
                "id": sc.id,
                "title": sc.title,
                "world": sc.world,
                "case_id": res["case"].id,
                "seconds": round(secs, 2),
                "cost_usd": round(res["ctx"].meter.cost_usd, 5),
                "model_mode": "llm" if llm.available() else "deterministic",
                **s,
            }
        )
    n = len(rows)
    accus = sum(len(r["causes"]) for r in rows)
    errs = [e for r in rows for e in r["share_abs_errors_pp"]]
    abst = [r for r in rows if r["expected_kind"] != "causes"]
    summary = {
        "scenarios": n,
        "top_cause_accuracy": sum(r["top_cause_ok"] for r in rows) / n if n else 0,
        "top_cause_correct": sum(r["top_cause_ok"] for r in rows),
        "share_mae_pp": round(sum(errs) / len(errs), 2) if errs else None,
        "false_accusations": sum(len(r["false_accusations"]) for r in rows),
        "false_accusation_rate": (sum(len(r["false_accusations"]) for r in rows) / accus) if accus else 0.0,
        "correct_abstention": f"{sum(r['kind_ok'] for r in abst)}/{len(abst)}",
        "missed_causes": sum(len(r["missed"]) for r in rows),
        "mean_seconds": round(sum(r["seconds"] for r in rows) / n, 2) if n else 0,
        "mean_cost_usd": round(sum(r["cost_usd"] for r in rows) / n, 5) if n else 0,
        "model_mode": rows[0]["model_mode"] if rows else None,
    }
    out = {"generated_at": datetime.now(UTC).isoformat(), "summary": summary, "scenarios": rows}
    if not only:
        RESULTS.write_text(json.dumps(out, indent=2, default=str) + "\n")
    return out


def table(out: dict[str, Any]) -> str:
    s = out["summary"]
    lines = [
        "| ID | Scenario | Verdict | Top cause right | Share error (pp) | False accusations | Time | Cost |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in out["scenarios"]:
        err = ", ".join(f"{e:.1f}" for e in r["share_abs_errors_pp"]) or "–"
        lines.append(
            f"| {r['id']} | {r['title']} | {r['verdict_kind'].replace('_', ' ')} | "
            f"{'yes' if r['top_cause_ok'] else '**no**'} | {err} | {len(r['false_accusations'])} | "
            f"{r['seconds']:.1f} s | ${r['cost_usd']:.4f} |"
        )
    lines += [
        "",
        f"**Top-cause accuracy {s['top_cause_correct']}/{s['scenarios']}** · share MAE "
        f"{s['share_mae_pp']} pp · false accusations {s['false_accusations']} "
        f"({s['false_accusation_rate'] * 100:.0f}%) · correct abstention {s['correct_abstention']} · "
        f"missed causes {s['missed_causes']} · mean {s['mean_seconds']} s and ${s['mean_cost_usd']:.4f} per case "
        f"({s['model_mode']} mode)",
    ]
    return "\n".join(lines)


async def main(only: list[str] | None = None) -> dict[str, Any]:
    try:
        return await run_all(only)
    finally:
        await db.close_pool()
