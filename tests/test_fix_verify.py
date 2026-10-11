"""Stage 11: fixes, approval gates, verification and the watcher (fixture worlds; live paths need credentials)."""

from datetime import UTC, datetime, timedelta

import pytest

from engine.agents import fixer
from engine.fixtures.world import WorldSpec, generate
from engine.runtime import events as ev
from engine.runtime.orchestrator import investigate
from engine.runtime.verify import verify_case
from engine.runtime.watcher import detect, watch_once


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "")
    from engine.runtime import llm as llm_mod

    llm_mod.set_llm(None)
    yield
    llm_mod.set_llm(None)


async def test_fixture_fixes_are_proposals_only(pg):
    res = await investigate("fixture:3inc")
    cid = res["case"].id
    fixes = await pg.fetch("SELECT * FROM fixes WHERE case_id = %s ORDER BY created_at", (cid,))
    assert {f["type"] for f in fixes} == {"code_pr", "config", "recommendation"}
    assert all(f["status"] == "proposed_only" for f in fixes)
    with pytest.raises(fixer.FixError, match="proposal only"):
        await fixer.approve(fixes[0]["id"])
    types = [e["type"] for e in await ev.events_since(cid)]
    assert types.count("fix_proposed") == 3 and types.index("investigation_complete") < types.index(
        "fix_proposed"
    )


@pytest.fixture(scope="module")
def fixed_world():
    # A Safari bug from day 8 that is fixed (ends) 48 hours later; the case window covers the bug.
    spec = WorldSpec(
        name="bug_then_fix",
        start=datetime(2026, 9, 14).date(),
        days=14,
        incidents="deploy_bug:webkit:hours=48@8d10h",
        case={"window": ["8d", "10d"], "baseline": "wow"},
    )
    return generate(spec, ground_truth=False)


async def test_verification_closes_after_recovery_and_waits_before(pg, fixed_world):
    res = await investigate("fixture:bug_then_fix")
    assert res["verdict"]["kind"] == "causes"
    cid = res["case"].id
    fix = await pg.fetchrow("SELECT * FROM fixes WHERE case_id = %s AND type = 'code_pr'", (cid,))
    bug_end = datetime(2026, 9, 24, 10, tzinfo=UTC)
    # Pretend the fix was merged too early (while the bug is still live): not recovered.
    await pg.execute(
        "UPDATE fixes SET status = 'monitoring', applied_at = %s WHERE id = %s",
        (bug_end - timedelta(hours=20), fix["id"]),
    )
    r = await verify_case(cid, now=bug_end - timedelta(hours=2))
    assert not r["closed"] and r["results"][0]["status"] == "not_recovered"
    # The real fix lands when the bug ends: recovered, case closed.
    await pg.execute("UPDATE fixes SET applied_at = %s WHERE id = %s", (bug_end, fix["id"]))
    r = await verify_case(cid, now=bug_end + timedelta(hours=14))
    assert r["closed"] and r["results"][0]["status"] == "recovered"
    types = [e["type"] for e in await ev.events_since(cid)]
    assert types[-1] == "case_closed"
    assert (await pg.fetchrow("SELECT status FROM cases WHERE id = %s", (cid,)))["status"] == "closed"


async def test_watcher_detects_sustained_drop_and_opens_case(pg):
    d = await detect("fixture:3inc", datetime(2026, 9, 28, tzinfo=UTC))
    assert d["sustained_drop"]
    quiet = await detect("fixture:noise", datetime(2026, 9, 28, tzinfo=UTC))
    assert not quiet["sustained_drop"]
    await pg.execute("UPDATE cases SET status = 'closed' WHERE world = 'fixture:3inc'")
    out = await watch_once("fixture:3inc", datetime(2026, 9, 28, tzinfo=UTC))
    assert out["opened"]
    case = await pg.fetchrow("SELECT auto_opened, status FROM cases WHERE id = %s", (out["opened"],))
    assert case["auto_opened"] and case["status"] in ("verdict", "fixing")
    again = await watch_once("fixture:3inc", datetime(2026, 9, 28, 1, tzinfo=UTC))
    assert again["opened"] is None and "still open" in again["skipped_detection"]
