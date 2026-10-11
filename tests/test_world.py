"""Stage 4 "done when": every fixture world generates in under 30 s and every incident's signal is in the data."""

from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from engine.fixtures.world import WorldSpec, generate, load_meta


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    d = tmp_path_factory.mktemp("worlds")
    out = {}
    for name in [
        "3inc",
        "holiday_red_herring",
        "noise",
        "outage",
        "competitor",
        "tracking",
        "seasonality",
        "seasonality_small_bug",
    ]:
        res = generate(WorldSpec.preset(name), d / f"{name}.duckdb", ground_truth=name == "3inc")
        assert res.seconds < 30, f"{name} took {res.seconds:.1f}s"
        out[name] = res
    return out


def q(res, sql, *params):
    with duckdb.connect(str(res.path), read_only=True) as con:
        return con.execute(sql, list(params)).fetchall()


def inc_start(res, kind):
    return datetime.fromisoformat(next(i["start"] for i in res.meta["incidents"] if i["kind"] == kind))


def test_3inc_deploy_bug_signal(worlds):
    w = worlds["3inc"]
    t = inc_start(w, "deploy_bug")
    webkit = "(os IN ('iOS','iPadOS') OR browser = 'Safari')"
    before = q(w, f"SELECT count(*) FROM events WHERE name='signup_completed' AND {webkit} AND ts < ?", t)[0][
        0
    ]
    after = q(w, f"SELECT count(*) FROM events WHERE name='signup_completed' AND {webkit} AND ts >= ?", t)[0][
        0
    ]
    others = q(
        w, f"SELECT count(*) FROM events WHERE name='signup_completed' AND NOT {webkit} AND ts >= ?", t
    )[0][0]
    # visitors mid-signup when the bug shipped may still finish; nobody after
    assert before > 200 and after <= 3 and others > 100
    # The first failing deployment carries the real diff, and WebKit flows fail from it onwards.
    first_bad = q(
        w,
        """SELECT d.created_at, d.diff FROM deployments d JOIN flow_results f ON f.deployment_id = d.id
                        WHERE NOT f.ok ORDER BY d.created_at LIMIT 1""",
    )[0]
    assert "requestIdleCallback" in first_bad[1]
    assert abs((first_bad[0] - t).total_seconds()) < 600
    assert q(w, "SELECT bool_and(ok) FROM flow_results WHERE probe LIKE 'chromium%'")[0][0]
    # Recordings of blocked users show repeated clicks on the same button.
    assert (
        q(
            w,
            """SELECT count(*) FROM replays r JOIN sessions s ON s.id = r.session_id
                   WHERE s.signup_blocked""",
        )[0][0]
        >= 10
    )


def test_3inc_ads_and_payments_signal(worlds):
    w = worlds["3inc"]
    t_ads = inc_start(w, "ads_budget_cap")
    limited = q(
        w, "SELECT count(*) FROM ads_hourly WHERE campaign_id='1002' AND budget_limited AND hour >= ?", t_ads
    )
    assert limited[0][0] >= 3
    assert (
        q(
            w,
            "SELECT count(*) FROM ads_hourly WHERE campaign_id='1002' AND budget_limited AND hour < ?",
            t_ads,
        )[0][0]
        == 0
    )
    ch = q(w, "SELECT user_email, old_value, new_value FROM ads_changes WHERE campaign_id='1002'")
    assert ch == [("jordan@acme-notes.test", 450.0, 150.0)]
    paid = q(
        w,
        """SELECT ts >= ? AS after, count(*) / count(DISTINCT date_trunc('day', ts)) FROM events
                   WHERE name='page_view' AND path='/' AND channel='paid' GROUP BY 1 ORDER BY 1""",
        t_ads,
    )
    assert paid[1][1] < 0.75 * paid[0][1]

    t_pay = inc_start(w, "payment_declines")
    rate = dict(
        q(
            w,
            """SELECT created >= ?, avg(CASE WHEN outcome_type='issuer_declined' THEN 1 ELSE 0 END)
                        FROM payments WHERE metadata_country='BR' GROUP BY 1""",
            t_pay,
        )
    )
    assert rate[False] < 0.10 and rate[True] > 0.18
    other = q(
        w,
        """SELECT avg(CASE WHEN outcome_type='issuer_declined' THEN 1 ELSE 0 END) FROM payments
                    WHERE metadata_country <> 'BR' AND created >= ?""",
        t_pay,
    )[0][0]
    assert other < 0.08


def test_3inc_ground_truth_shares(worlds):
    truth = worlds["3inc"].meta["truth"]
    shares = {k: v["share"] for k, v in truth["incidents"].items()}
    assert abs(sum(shares.values()) - 1) < 1e-6
    assert shares["deploy_bug:webkit"] > shares["ads_budget_cap"] > shares["payment_declines:BR"] > 0.03
    assert truth["actual_paid_subs"] < truth["counterfactual_paid_subs"]
    assert load_meta(worlds["3inc"].path)["case"]["baseline_mode"] == "wow"


def test_holiday_and_red_herring(worlds):
    w = worlds["holiday_red_herring"]
    day = inc_start(w, "public_holiday").date()
    de = q(
        w,
        """SELECT CAST(started_at AS DATE) = ? AS hol, count(*) / count(DISTINCT CAST(started_at AS DATE))
                 FROM sessions WHERE country = 'US' GROUP BY 1""",
        day,
    )
    by = dict(de)
    assert by[True] < 0.55 * by[False]
    assert q(w, "SELECT name FROM holidays WHERE country='US' AND date = ?", day.isoformat()) == [
        ("Labour Day",)
    ]
    assert (
        q(w, "SELECT count(*) FROM deployments WHERE commit_message LIKE 'copy: update German%'")[0][0] == 1
    )
    assert q(w, "SELECT bool_and(ok) FROM flow_results")[0][0]  # the deploy is harmless


def test_outage(worlds):
    w = worlds["outage"]
    t = inc_start(w, "dependency_outage")
    errs = dict(
        q(
            w,
            """SELECT created >= ? AND created < ? + INTERVAL 6 HOUR, avg(CASE WHEN error_code IS NOT NULL
                        THEN 1 ELSE 0 END) FROM payments GROUP BY 1""",
            t,
            t,
        )
    )
    assert errs[True] > 0.35 and errs[False] < 0.02
    assert q(w, "SELECT impact FROM status_incidents WHERE service='Stripe'") == [("major",)]


def test_competitor_launch(worlds):
    w = worlds["competitor"]
    t = inc_start(w, "competitor_launch")
    assert q(w, "SELECT count(*) FROM news WHERE title LIKE 'Quillboard launches%'")[0][0] == 1
    r = dict(
        q(
            w,
            """SELECT s.started_at >= ?, avg(CASE WHEN e.session_id IS NOT NULL THEN 1 ELSE 0 END)
                     FROM sessions s LEFT JOIN (SELECT DISTINCT session_id FROM events WHERE name='signup_started') e
                     ON e.session_id = s.id GROUP BY 1""",
            t,
        )
    )
    assert r[True] < 0.9 * r[False]


def test_tracking_bug_is_measurement_only(worlds):
    w = worlds["tracking"]
    t = inc_start(w, "tracking_bug")
    # visitors mid-signup when the bug shipped may still send one; nobody after
    assert q(w, "SELECT count(*) FROM events WHERE name='signup_completed' AND ts >= ?", t)[0][0] <= 3
    # Real signups (Acme's own users table) are on par with the same hours one week earlier.
    end = datetime.fromisoformat(w.meta["end"])
    week = timedelta(days=7)
    now_n = q(w, "SELECT count(*) FROM users WHERE created_at >= ? AND created_at < ?", t, end)[0][0]
    then_n = q(
        w, "SELECT count(*) FROM users WHERE created_at >= ? AND created_at < ?", t - week, end - week
    )[0][0]
    assert now_n > 0.85 * then_n
    assert q(w, "SELECT count(*) FROM payments WHERE status='succeeded' AND created >= ?", t)[0][0] > 50


def test_noise_and_seasonality(worlds):
    assert worlds["noise"].meta["truth"] is None or not worlds["noise"].meta["truth"]["incidents"]
    w = worlds["seasonality"]
    case = w.meta["case"]
    w0 = datetime.fromisoformat(case["window_start"])
    assert w0.weekday() == 5 and case["baseline_mode"] == "preceding"
    per_day = dict(
        q(
            w,
            """SELECT CAST(started_at AS DATE) >= ?, count(*) / count(DISTINCT CAST(started_at AS DATE))
                           FROM sessions WHERE started_at >= ? GROUP BY 1""",
            w0.date(),
            datetime.fromisoformat(case["baseline_start"]),
        )
    )
    assert per_day[True] < 0.85 * per_day[False]


def test_firefox_variant(worlds):
    w = worlds["seasonality_small_bug"]
    t = inc_start(w, "deploy_bug")
    assert (
        q(
            w,
            "SELECT count(*) FROM events WHERE name='signup_completed' AND browser='Firefox' AND ts >= ?",
            t,
        )[0][0]
        == 0
    )
    assert (
        q(w, "SELECT count(*) FROM events WHERE name='signup_completed' AND browser='Safari' AND ts >= ?", t)[
            0
        ][0]
        > 0
    )


def test_determinism(tmp_path):
    a = generate(WorldSpec.preset("payments_only"), tmp_path / "a.duckdb", ground_truth=False)
    b = generate(WorldSpec.preset("payments_only"), tmp_path / "b.duckdb", ground_truth=False)
    assert q(a, "SELECT count(*), sum(amount) FROM payments") == q(
        b, "SELECT count(*), sum(amount) FROM payments"
    )
    assert a.counts == b.counts
    _ = UTC
