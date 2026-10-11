"""Counterfactual attribution: how much of the drop does each hypothesis explain?

Each hypothesis maps to an *effect*: (factor, segment, start[, end]). Restoring an effect puts that
factor back to its baseline value for that segment from that time on (traffic: the baseline's visitors
for the same hours, scaled by the unaffected traffic trend; rates: the segment's baseline rate).

The window is split into groups of (segment dims × which effects are active). The metric with a subset
S of effects restored is v(S) = Σ_g T'·s'·k'·p'. With nothing restored this reproduces the actual window
exactly, because T·(S/T)·(K/S)·(P/K) = P. Each effect's fair share of the loss is its exact Shapley value
over all subsets, and the residual is reported as "unexplained". Confidence intervals come from a
parametric bootstrap of every count in the model.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import polars as pl

from engine.analysis.data import FACTORS, Period

ALPHA = 20.0  # pseudo-count shrinkage of segment baseline rates toward the global baseline rate


@dataclass
class Effect:
    id: str
    factor: str
    segment: dict[str, Any] = field(default_factory=dict)
    start: datetime | None = None
    end: datetime | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if self.factor not in FACTORS:
            raise ValueError(f"unknown factor {self.factor!r}")


@dataclass
class _Model:
    effects: list[Effect]
    groups: pl.DataFrame
    dims: list[str]
    T: np.ndarray
    S: np.ndarray
    K: np.ndarray
    P: np.ndarray
    T0: np.ndarray
    dim_idx: np.ndarray
    base: dict[str, np.ndarray]  # per dims-combo baseline counts: T, S, K, P
    active: np.ndarray  # groups × effects (bool)
    unaffected_traffic: np.ndarray  # groups that no traffic effect ever touches
    baseline_paid: float


def _effect_dims(effects: list[Effect]) -> list[str]:
    dims: list[str] = []
    for e in effects:
        for d in e.segment:
            if d not in dims:
                dims.append(d)
    return dims


def _in_segment(df: pl.DataFrame, seg: dict[str, Any]) -> pl.Expr:
    expr = pl.lit(True)
    for d, v in seg.items():
        vals = list(v) if isinstance(v, list | tuple | set) else [v]
        expr = expr & pl.col(d).is_in(vals)
    return expr


def build_model(sess: pl.DataFrame, effects: list[Effect], baseline: Period, window: Period) -> _Model:
    dims = _effect_dims(effects)
    keys = dims or ["_all"]
    s = sess.with_columns(pl.lit("all").alias("_all")) if not dims else sess
    win = window.filter(s).with_columns(pl.col("started_at").dt.truncate("1h").alias("hour"))
    bas = baseline.filter(s).with_columns(pl.col("started_at").dt.truncate("1h").alias("hour"))

    agg = [
        pl.len().alias("T"),
        pl.col("signed_up").sum().alias("S"),
        pl.col("checkout").sum().alias("K"),
        pl.col("paid").sum().alias("P"),
    ]
    obs = win.group_by(keys + ["hour"]).agg(agg)

    # Expected baseline visitors for each (dims, hour) of the window.
    offset = window.start - baseline.start
    aligned = offset.days % 7 == 0 and offset.seconds == 0 and abs(window.days - baseline.days) < 1e-9
    if aligned:
        t0 = (
            bas.group_by(keys + ["hour"])
            .agg(pl.len().alias("T0"))
            .with_columns((pl.col("hour") + offset).alias("hour"))
        )
    else:
        prof = (
            bas.group_by(keys + [pl.col("hour").dt.hour().alias("hod")])
            .agg(pl.len().alias("n"))
            .with_columns((pl.col("n") / baseline.days).alias("T0"))
            .drop("n")
        )
        t0 = None
    combos = pl.concat([win.select(keys), bas.select(keys)]).unique()
    hours = pl.DataFrame(
        {
            "hour": pl.datetime_range(
                window.start, window.end - timedelta(hours=1), "1h", time_zone="UTC", eager=True
            )
        }
    )
    grid = combos.join(hours, how="cross").join(obs, on=keys + ["hour"], how="left")
    if aligned:
        grid = grid.join(t0, on=keys + ["hour"], how="left")
    else:
        grid = (
            grid.with_columns(pl.col("hour").dt.hour().alias("hod"))
            .join(prof, on=keys + ["hod"], how="left")
            .drop("hod")
        )
    grid = grid.fill_null(0)

    # Which effects are active in each cell (an hour counts once at least half of it is after the start).
    flags = []
    for i, e in enumerate(effects):
        mid = pl.col("hour") + timedelta(minutes=30)
        cond = _in_segment(grid, e.segment)
        if e.start is not None:
            cond = cond & (mid >= e.start)
        if e.end is not None:
            cond = cond & (mid < e.end)
        flags.append(cond.alias(f"e{i}"))
    traffic_ids = [i for i, e in enumerate(effects) if e.factor == "traffic"]
    touched = pl.lit(False)
    for i in traffic_ids:
        touched = touched | _in_segment(grid, effects[i].segment)
    grid = (
        grid.with_columns(*flags, touched.alias("touched"))
        if flags
        else grid.with_columns(touched.alias("touched"))
    )
    ecols = [f"e{i}" for i in range(len(effects))]
    groups = grid.group_by(keys + ecols + ["touched"]).agg(
        pl.col("T").sum(), pl.col("S").sum(), pl.col("K").sum(), pl.col("P").sum(), pl.col("T0").sum()
    )

    # Baseline counts per dims combo.
    base_tab = bas.group_by(keys).agg(agg)
    combos_list = combos.sort(keys)
    base_tab = combos_list.join(base_tab, on=keys, how="left").fill_null(0)
    combo_index = {tuple(r): i for i, r in enumerate(base_tab.select(keys).iter_rows())}
    dim_idx = np.array([combo_index[tuple(r)] for r in groups.select(keys).iter_rows()], dtype=int)

    return _Model(
        effects=effects,
        groups=groups,
        dims=dims,
        T=groups["T"].to_numpy().astype(float),
        S=groups["S"].to_numpy().astype(float),
        K=groups["K"].to_numpy().astype(float),
        P=groups["P"].to_numpy().astype(float),
        T0=groups["T0"].to_numpy().astype(float),
        dim_idx=dim_idx,
        base={c: base_tab[c].to_numpy().astype(float) for c in ("T", "S", "K", "P")},
        active=groups.select(ecols).to_numpy().astype(bool) if ecols else np.zeros((groups.height, 0), bool),
        unaffected_traffic=~groups["touched"].to_numpy().astype(bool),
        baseline_paid=float(bas["paid"].sum()) * (window.days / baseline.days),
    )


def _ratio(num: np.ndarray, den: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(den > 0, num / np.where(den > 0, den, 1), fallback)
    return r


def _pooled(num: np.ndarray, den: np.ndarray, key: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """Pooled rate over groups sharing `key` (and den > 0); fallback where none."""
    out = fallback.copy()
    for k in np.unique(key):
        m = key == k
        d = den[m].sum()
        if d > 0:
            out[m] = num[m].sum() / d
    return out


def _values(
    m: _Model,
    T: np.ndarray,
    S: np.ndarray,
    K: np.ndarray,
    P: np.ndarray,
    T0: np.ndarray,
    base: dict[str, np.ndarray],
) -> np.ndarray:
    """v(subset) for every subset bitmask 0 .. 2^n − 1."""
    n = len(m.effects)
    gT, gS, gK, gP = (base[c].sum() for c in ("T", "S", "K", "P"))
    g_s, g_k, g_p = gS / max(gT, 1), gK / max(gS, 1), gP / max(gK, 1)
    s0 = ((base["S"] + ALPHA * g_s) / (base["T"] + ALPHA))[m.dim_idx]
    k0 = ((base["K"] + ALPHA * g_k) / (base["S"] + ALPHA))[m.dim_idx]
    p0 = ((base["P"] + ALPHA * g_p) / (base["K"] + ALPHA))[m.dim_idx]

    def pattern(factor: str) -> np.ndarray:
        ids = [i for i, e in enumerate(m.effects) if e.factor == factor]
        if not ids:
            return np.zeros(len(T), dtype=int)
        bits = m.active[:, ids].astype(int)
        return bits @ (1 << np.arange(len(ids)))

    # Raw group rates reproduce the actual window exactly. Once an upstream factor is restored in a group,
    # its downstream rates are multiplied by restored (larger) volumes, so they use shrunk estimates instead:
    # the group's rate pulled toward its segment's pooled window rate, itself pulled toward the window-wide
    # rate for groups in the same effect state.
    def shrunk(num: np.ndarray, den: np.ndarray, factor: str, fb: np.ndarray) -> np.ndarray:
        pat = pattern(factor)
        glob = _pooled(num, den, pat, fb)
        seg = _pooled_shrunk(num, den, m.dim_idx * 1000 + pat, glob)
        return (num + ALPHA * seg) / (den + ALPHA)

    s_raw, k_raw, p_raw = _ratio(S, T, s0), _ratio(K, S, k0), _ratio(P, K, p0)
    s_sh = shrunk(S, T, "signup_rate", s0)
    k_sh = shrunk(K, S, "checkout_rate", k0)
    p_sh = shrunk(P, K, "payment_success_rate", p0)
    unaff = m.unaffected_traffic
    trend = T[unaff].sum() / T0[unaff].sum() if T0[unaff].sum() > 0 else 1.0
    T0adj = T0 * trend

    vals = np.zeros(1 << n)
    for mask in range(1 << n):
        restore = {f: np.zeros(len(T), dtype=bool) for f in FACTORS}
        for i, e in enumerate(m.effects):
            if mask >> i & 1:
                restore[e.factor] |= m.active[:, i]
        up = restore["traffic"]
        t = np.where(up, T0adj, T)
        s = np.where(restore["signup_rate"], s0, np.where(up, s_sh, s_raw))
        up = up | restore["signup_rate"]
        k = np.where(restore["checkout_rate"], k0, np.where(up, k_sh, k_raw))
        up = up | restore["checkout_rate"]
        p = np.where(restore["payment_success_rate"], p0, np.where(up, p_sh, p_raw))
        vals[mask] = float(np.sum(t * s * k * p))
    return vals


def _pooled_shrunk(num: np.ndarray, den: np.ndarray, key: np.ndarray, prior: np.ndarray) -> np.ndarray:
    out = prior.copy()
    for k in np.unique(key):
        msk = key == k
        out[msk] = (num[msk].sum() + ALPHA * prior[msk]) / (den[msk].sum() + ALPHA)
    return out


def _shapley(vals: np.ndarray, n: int) -> np.ndarray:
    phi = np.zeros(n)
    fact = [math.factorial(i) for i in range(n + 1)]
    for i in range(n):
        for mask in range(1 << n):
            if mask >> i & 1:
                continue
            size = bin(mask).count("1")
            w = fact[size] * fact[n - size - 1] / fact[n]
            phi[i] += w * (vals[mask | (1 << i)] - vals[mask])
    return phi


def attribute(
    sess: pl.DataFrame,
    effects: list[Effect],
    baseline: Period,
    window: Period,
    *,
    n_boot: int = 300,
    seed: int = 0,
    ci: float = 0.9,
) -> dict[str, Any]:
    if len(effects) > 7:
        raise ValueError("exact Shapley is limited to 7 hypotheses")
    m = build_model(sess, effects, baseline, window)
    n = len(effects)
    vals = _values(m, m.T, m.S, m.K, m.P, m.T0, m.base)
    phi = _shapley(vals, n)
    actual = float(m.P.sum())
    drop = m.baseline_paid - actual

    # Parametric bootstrap of every count.
    rng = np.random.default_rng(seed)
    boot_phi = np.zeros((n_boot, n))
    boot_drop = np.zeros(n_boot)
    for b in range(n_boot):
        T = rng.poisson(m.T).astype(float)
        S = rng.binomial(T.astype(int), _ratio(m.S, m.T, np.zeros_like(m.T)).clip(0, 1)).astype(float)
        K = rng.binomial(S.astype(int), _ratio(m.K, m.S, np.zeros_like(m.S)).clip(0, 1)).astype(float)
        P = rng.binomial(K.astype(int), _ratio(m.P, m.K, np.zeros_like(m.K)).clip(0, 1)).astype(float)
        T0 = rng.poisson(m.T0).astype(float)
        bT = rng.poisson(m.base["T"]).astype(float)
        bS = rng.binomial(
            bT.astype(int), _ratio(m.base["S"], m.base["T"], np.zeros_like(bT)).clip(0, 1)
        ).astype(float)
        bK = rng.binomial(
            bS.astype(int), _ratio(m.base["K"], m.base["S"], np.zeros_like(bT)).clip(0, 1)
        ).astype(float)
        bP = rng.binomial(
            bK.astype(int), _ratio(m.base["P"], m.base["K"], np.zeros_like(bT)).clip(0, 1)
        ).astype(float)
        v = _values(m, T, S, K, P, T0, {"T": bT, "S": bS, "K": bK, "P": bP})
        boot_phi[b] = _shapley(v, n)
        bp = m.baseline_paid * (bP.sum() / m.base["P"].sum()) if m.base["P"].sum() else m.baseline_paid
        boot_drop[b] = bp - P.sum()

    lo_q, hi_q = (1 - ci) / 2 * 100, (1 + ci) / 2 * 100
    explained = float(phi.sum())
    tot = boot_phi.sum(axis=1, keepdims=True)
    be = boot_phi / np.where(tot > 0, tot, np.nan)
    out_effects = []
    for i, e in enumerate(effects):
        share_d = phi[i] / drop if drop > 0 else 0.0
        bs = boot_phi[:, i] / np.where(boot_drop > 0, boot_drop, np.nan)
        out_effects.append(
            {
                "id": e.id,
                "label": e.label,
                "factor": e.factor,
                "segment": e.segment,
                "start": e.start.isoformat() if e.start else None,
                "lost": float(phi[i]),
                "lost_ci": [
                    float(np.percentile(boot_phi[:, i], lo_q)),
                    float(np.percentile(boot_phi[:, i], hi_q)),
                ],
                "share_of_drop": float(share_d),
                "share_of_drop_ci": [float(np.nanpercentile(bs, lo_q)), float(np.nanpercentile(bs, hi_q))],
                "share_of_explained": float(phi[i] / explained) if explained > 0 else 0.0,
                "share_of_explained_ci": [
                    float(np.nanpercentile(be[:, i], lo_q)),
                    float(np.nanpercentile(be[:, i], hi_q)),
                ],
            }
        )
    out_effects.sort(key=lambda r: -r["lost"])
    unexplained = drop - explained
    ub = (boot_drop - boot_phi.sum(axis=1)) / np.where(boot_drop > 0, boot_drop, np.nan)
    return {
        "metric": "paid_subs",
        "baseline": baseline.as_dict(),
        "window": window.as_dict(),
        "baseline_expected": m.baseline_paid,
        "actual": actual,
        "observed_drop": drop,
        "counterfactual": float(vals[-1]),
        "explained": explained,
        "effects": out_effects,
        "unexplained": {
            "lost": float(unexplained),
            "share_of_drop": float(unexplained / drop) if drop > 0 else 0.0,
            "share_of_drop_ci": [float(np.nanpercentile(ub, lo_q)), float(np.nanpercentile(ub, hi_q))],
        },
        "check_v_empty_equals_actual": float(vals[0] - actual),
        "n_boot": n_boot,
        "ci": ci,
    }


def all_subsets(n: int) -> list[tuple[int, ...]]:
    return [c for r in range(n + 1) for c in itertools.combinations(range(n), r)]
