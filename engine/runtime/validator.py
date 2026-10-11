"""The validator: code, not a model, decides whether a finding may stand.

A finding is rejected when it cites no evidence, cites evidence that doesn't exist in this case, refers to
metrics that were never computed, or states a number that doesn't match one of the metrics it references.
Accepted findings have their confidence scaled by the weakest evidence tier they rely on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from engine.runtime.schemas import Finding, MetricRef

# Things that look like numbers but are not claims: dates, times, ids, versions, years.
_STRIP = [
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b",  # ISO dates/times
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\s*(?:UTC|GMT|am|pm)?\b",  # 10:00, 21:30 UTC
    r"\b\d{1,2}\s*(?:am|pm)\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\b",
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\b",
    r"\b(?:ev|m|f|h|q|case|dpl|pi|cus|sub|s|a|u|pa)_[A-Za-z0-9_]+\b",  # ids
    r"#\d+\b",
    r"\bv\d+(?:\.\d+)*\b",
    r"\b20[2-3]\d\b",
    r"\bT\+\d+(?:\.\d+)?[dhm]\b",
    r"\b[0-9a-f]{7,40}\b",  # git shas
    r"\b(?:iPhone|Pixel|Safari|iOS|Android|Chrome|Firefox|macOS|Windows)\s*\d+(?:\.\d+)*\b",
]
_NUM = re.compile(r"(?<![\w.])([-−+]?\$?\d[\d,]*(?:\.\d+)?)\s*(%|pp\b|percentage points?|k\b|×|x\b)?", re.I)
_MONEY_CHANGE = re.compile(r"\$(\d[\d,]*(?:\.\d+)?)\s*(?:→|->|to)\s*\$(\d[\d,]*(?:\.\d+)?)")


@dataclass
class Number:
    value: float
    decimals: int
    suffix: str
    text: str


_QUOTED = re.compile(r"“[^”]*”|\"[^\"]{12,}\"")


def extract_numbers(text: str) -> list[Number]:
    """Numbers stated as claims. Quoted customer text (“…”) is evidence, not a claim, so it is skipped."""
    text = _QUOTED.sub(" ", text)
    out: list[Number] = []
    for a, b in _MONEY_CHANGE.findall(text):
        for t in (a, b):
            out.append(
                Number(float(t.replace(",", "")), len(t.split(".")[1]) if "." in t else 0, "$", "$" + t)
            )
    clean = _MONEY_CHANGE.sub(" ", text)
    for pat in _STRIP:
        clean = re.sub(pat, " ", clean, flags=re.I)
    for m in _NUM.finditer(clean):
        raw, suffix = m.group(1), (m.group(2) or "").lower()
        num = raw.replace("−", "-").replace("$", "").replace(",", "")
        try:
            v = float(num)
        except ValueError:
            continue
        dec = len(num.split(".")[1]) if "." in num else 0
        if suffix == "k":
            v, suffix = v * 1000, ""
        if suffix.startswith("percentage"):
            suffix = "pp"
        out.append(Number(abs(v), dec, suffix, m.group(0).strip()))
    return out


def _candidates(m: MetricRef, pct: bool) -> list[float]:
    v = m.value
    if pct:
        return [abs(v) * 100] if m.unit in ("rate", "share", "pct_change") else [abs(v)]
    vals = [abs(v)]
    if m.unit in ("rate", "share", "pct_change"):
        vals.append(abs(v) * 100)
    return vals


def number_matches(n: Number, metrics: list[MetricRef]) -> bool:
    pct = n.suffix in ("%", "pp")
    tol_digits = 0.5 * 10 ** (-n.decimals)
    for m in metrics:
        for c in _candidates(m, pct):
            if abs(n.value - c) <= tol_digits + 0.01 * abs(c) + 1e-9:
                return True
    return False


class Validator:
    def __init__(
        self, evidence: dict[str, Any], metrics: dict[str, MetricRef], tier_confidence: dict[str, float]
    ):
        self.evidence = evidence
        self.metrics = metrics
        self.tier_confidence = tier_confidence

    def problems(self, f: Finding) -> list[str]:
        out = []
        if not f.evidence_ids:
            out.append("cites no evidence")
        unknown = [e for e in f.evidence_ids if e not in self.evidence]
        if unknown:
            out.append(f"cites evidence that does not exist in this case: {', '.join(unknown)}")
        bad_refs = [r for r in f.metrics_refs if r not in self.metrics]
        if bad_refs:
            out.append(f"references metrics that were never computed: {', '.join(bad_refs)}")
        refs = [self.metrics[r] for r in f.metrics_refs if r in self.metrics]
        nums = extract_numbers(f.claim)
        unmatched = [n.text for n in nums if not number_matches(n, refs)]
        if unmatched:
            out.append(f"states numbers that match none of its referenced metrics: {', '.join(unmatched)}")
        return out

    def apply(self, f: Finding) -> Finding:
        """Set status/confidence. Accepted findings are scaled by the weakest evidence tier."""
        probs = self.problems(f)
        if probs:
            return f.model_copy(update={"status": "rejected", "rejection_reason": "; ".join(probs)})
        weakest = min((self.tier_confidence.get(e, 1.0) for e in f.evidence_ids), default=1.0)
        conf = round(min(f.confidence, 1.0) * weakest, 3)
        if f.kind == "inference":
            conf = round(conf * 0.85, 3)
        return f.model_copy(update={"status": "accepted", "confidence": conf})
