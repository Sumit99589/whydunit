"""Stage 6 "done when": the toolkit recovers ground-truth factors on fixture worlds, and Shapley shares are
within ±5 percentage points of ground truth on the 3-incident world."""

from datetime import UTC, datetime, timedelta

import pytest

from engine.analysis.bootstrap import rate_change_ci, rate_ci
from engine.analysis.changepoint import assess_change, cusum
from engine.analysis.data import Period, session_table
from engine.analysis.decompose import decompose
from engine.analysis.segments import drilldown, factor_by_segment
from engine.analysis.sessions import analyze, summarize
from engine.analysis.shapley import Effect, attribute
from engine.connectors.base import Window
from engine.connectors.fixture import FixtureWorld
from engine.fixtures.world import load_meta, resolve_world

FACTOR = {
    "deploy_bug": "signup_rate",
    "ads_budget_cap": "traffic",
    "payment_declines": "payment_success_rate",
    "public_holiday": "traffic",
    "dependency_outage": "payment_success_rate",
    "competitor_launch": "signup_rate",
    "checkout_slow": "checkout_rate",
}
SEGMENT = {
    "deploy_bug": lambda p: {"engine": p.get("arg", "webkit")},
    "ads_budget_cap": lambda p: {"channel": "paid"},
    "payment_declines": lambda p: {"country": p.get("arg", "BR")},
    "public_holiday": lambda p: {"country": p.get("arg", "DE")},
    "dependency_outage": lambda p: {},
    "competitor_launch": lambda p: {},
    "checkout_slow": lambda p: {},
}


class World:
    def __init__(self, name):
        self.path = resolve_world(f"fixture:{name}")
        self.meta = load_meta(self.path)
        c = self.meta["case"]
        self.B = Period(
            datetime.fromisoformat(c["baseline_start"]), datetime.fromisoformat(c["baseline_end"])
        )
        self.W = Period(datetime.fromisoformat(c["window_start"]), datetime.fromisoformat(c["window_end"]))
        self.start = datetime.fromisoformat(self.meta["start"])
        self.fw = FixtureWorld(self.path)

    async def sess(self):
        b = await self.fw.fetch("funnel_events", Window(self.start, datetime.fromisoformat(self.meta["end"])))
        return session_table(b.frame)

    def effects(self):
        out = []
        for i in self.meta["incidents"]:
            if not i["causal"] or i["kind"] not in FACTOR:
                continue
            out.append(
                Effect(
                    i["id"],
                    FACTOR[i["kind"]],
                    SEGMENT[i["kind"]](i["params"]),
                    datetime.fromisoformat(i["start"]),
                    datetime.fromisoformat(i["end"]) if i["end"] else None,
                )
            )
        return out


@pytest.fixture(scope="module")
def w3():
    return World("3inc")


async def test_decomposition_adds_up_and_points_at_signup_rate(w3):
    d = decompose(await w3.sess(), w3.B, w3.W)
    assert abs(d["check_sum"]) < 1e-9
    by = {f["factor"]: f for f in d["factors"]}
    assert d["change_per_day"] < 0
    assert by["signup_rate"]["contribution_per_day"] < by["traffic"]["contribution_per_day"] < 0
    assert by["payment_success_rate"]["contribution_per_day"] < 0


async def test_segments_find_the_planted_segments(w3):
    sess = await w3.sess()
    top_signup = drilldown(sess, "signup_rate", w3.B, w3.W, top=3)
    assert {(r["dim"], r["value"]) for r in top_signup} & {
        ("engine", "webkit"),
        ("os", "iOS"),
        ("browser", "Safari"),
    }
    eng = {r["value"]: r for r in factor_by_segment(sess, "signup_rate", "engine", w3.B, w3.W)}
    assert eng["webkit"]["share_of_factor_change"] > 0.85 and eng["webkit"]["window"] < 0.01
    ch = {r["value"]: r for r in factor_by_segment(sess, "traffic", "channel", w3.B, w3.W)}
    assert ch["paid"]["contribution"] < ch["organic"]["contribution"]
    assert ch["paid"]["contribution"] < -150
    ctry = factor_by_segment(sess, "payment_success_rate", "country", w3.B, w3.W)
    assert ctry[0]["value"] == "BR"


async def test_shapley_within_5pp_of_ground_truth(w3):
    sess = await w3.sess()
    a = attribute(sess, w3.effects(), w3.B, w3.W, n_boot=100)
    assert abs(a["check_v_empty_equals_actual"]) < 1e-6
    truth = w3.meta["truth"]["incidents"]
    for e in a["effects"]:
        assert abs(e["share_of_explained"] - truth[e["id"]]["share"]) <= 0.05, (
            e["id"],
            e["share_of_explained"],
            truth[e["id"]]["share"],
        )
        lo, hi = e["share_of_explained_ci"]
        assert lo <= e["share_of_explained"] <= hi
    assert [e["id"] for e in a["effects"]] == ["deploy_bug:webkit", "ads_budget_cap", "payment_declines:BR"]
    assert abs(a["unexplained"]["share_of_drop"]) < 0.25


async def test_change_detection_real_vs_noise():
    w = World("3inc")
    assert assess_change(await w.sess(), "paid", w.W, w.B, w.start)["verdict"] == "real_drop"
    n = World("noise")
    r = assess_change(await n.sess(), "paid", n.W, n.B, n.start)
    assert r["verdict"] == "within_normal_variance", r


async def test_weekend_dip_is_seasonal_not_real():
    s = World("seasonality")
    r = assess_change(await s.sess(), "paid", s.W, s.B, s.start)
    assert r["naive_relative_change_vs_baseline"] < -0.1  # looks like a drop vs the weekdays before
    assert r["verdict"] == "within_normal_variance"  # but it is the usual weekend


async def test_cusum_timing(w3):
    sess = await w3.sess()
    inc = {i["kind"]: datetime.fromisoformat(i["start"]) for i in w3.meta["incidents"]}
    for kind, factor, seg, tol in [
        ("deploy_bug", "signup_rate", {"engine": "webkit"}, 2),
        ("ads_budget_cap", "traffic", {"channel": "paid"}, 3),
        ("payment_declines", "payment_success_rate", {"country": "BR"}, 4),
    ]:
        c = cusum(sess, factor, w3.B, w3.W, seg)
        assert c["detected"], kind
        assert abs(datetime.fromisoformat(c["changed_at"]) - inc[kind]) <= timedelta(hours=tol), (
            kind,
            c,
            inc[kind],
        )
    assert not cusum(sess, "signup_rate", w3.B, w3.W, {"engine": "chromium"})["detected"]


@pytest.mark.parametrize("name", ["holiday_red_herring", "outage", "competitor", "seasonality_small_bug"])
async def test_attribution_other_worlds(name):
    w = World(name)
    effects = w.effects()
    a = attribute(await w.sess(), effects, w.B, w.W, n_boot=50)
    assert a["effects"][0]["lost"] > 0
    if name == "holiday_red_herring":
        assert [i["kind"] for i in w.meta["incidents"] if i["causal"]] == ["public_holiday"]


async def test_session_heuristics(w3):
    sess = await w3.sess()
    rep = (await w3.fw.fetch("sessions", w3.W, {"has_replay": True})).frame
    blocked_ids = set(sess.filter(~sess["signed_up"] & sess["engine"].eq("webkit"))["session_id"].to_list())
    results_blocked, results_ok = [], []
    for sid in rep["session_id"].to_list():
        r = analyze(await w3.fw.recording(sid))
        (
            results_blocked
            if sid in blocked_ids and not r["pages"][-1].endswith("/onboarding")
            else results_ok
        ).append(r)
    blocked = [r for r in results_blocked if r["clicks"] > 3]
    assert blocked and all(r["rage_bursts"] and r["dead_clicks"] >= 3 for r in blocked)
    assert all(b["element"] == "Create account" for r in blocked for b in r["rage_bursts"])
    assert all(r["form_abandoned"] for r in blocked)
    signed = [r for r in results_ok if r["pages"] and r["pages"][-1].endswith("/onboarding")]
    assert signed and all(not r["rage_bursts"] and not r["form_abandoned"] for r in signed)
    s = summarize(blocked)
    assert s["rage_elements"] == {"Create account": len(blocked)}
    assert blocked[0]["keyframe_times_ms"]


def test_bootstrap_helpers():
    lo, hi = rate_ci(50, 500)
    assert lo < 0.1 < hi
    c = rate_change_ci(95, 1000, 1, 1000)
    assert c["diff_hi"] < -0.06 and c["rel_hi"] < -0.9
    _ = UTC
