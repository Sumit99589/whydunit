"""Small bootstrap helpers for rates and rate differences (Shapley CIs live in shapley.py)."""

from __future__ import annotations

import numpy as np


def rate_ci(x: int, n: int, *, ci: float = 0.95, n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    draws = rng.binomial(n, x / n, n_boot) / n
    return float(np.percentile(draws, (1 - ci) / 2 * 100)), float(np.percentile(draws, (1 + ci) / 2 * 100))


def rate_change_ci(
    x0: int, n0: int, x1: int, n1: int, *, ci: float = 0.95, n_boot: int = 4000, seed: int = 0
) -> dict[str, float]:
    """Bootstrap CI for r1 − r0 and r1 / r0 − 1."""
    rng = np.random.default_rng(seed)
    r0 = rng.binomial(max(n0, 1), x0 / n0 if n0 else 0.0, n_boot) / max(n0, 1)
    r1 = rng.binomial(max(n1, 1), x1 / n1 if n1 else 0.0, n_boot) / max(n1, 1)
    lo, hi = (1 - ci) / 2 * 100, (1 + ci) / 2 * 100
    diff = r1 - r0
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(r0 > 0, r1 / r0 - 1, np.nan)
    return {
        "diff": (x1 / n1 if n1 else 0) - (x0 / n0 if n0 else 0),
        "diff_lo": float(np.percentile(diff, lo)),
        "diff_hi": float(np.percentile(diff, hi)),
        "rel_lo": float(np.nanpercentile(rel, lo)),
        "rel_hi": float(np.nanpercentile(rel, hi)),
    }
