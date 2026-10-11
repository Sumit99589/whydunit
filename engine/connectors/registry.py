"""Resolve the best available connector for each evidence kind, walking the connector ladder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.connectors.base import KINDS, TIERS, Connector, ConnectorUnavailable, EvidenceBundle, Window


@dataclass
class LadderStep:
    connector: str
    tier: int
    available: bool
    reason: str = ""


@dataclass
class NoSource(ConnectorUnavailable):
    """No connector could supply a kind: the detective must say `cannot_determine`."""

    kind: str
    ladder: list[LadderStep] = field(default_factory=list)

    def __str__(self) -> str:
        tried = ", ".join(f"{s.connector} (tier {s.tier}: {s.reason or 'unavailable'})" for s in self.ladder)
        return f"no source for {self.kind}; tried {tried or 'nothing configured'}"


class Registry:
    def __init__(self, connectors: list[Connector], *, mode: str = "live", label: str = ""):
        self.connectors = connectors
        self.mode = mode
        self.label = label
        self._avail: dict[str, bool] = {}
        self._failed: dict[str, str] = {}

    def candidates(self, kind: str) -> list[Connector]:
        cs = [c for c in self.connectors if kind in c.kinds]
        return sorted(cs, key=lambda c: (_tier(c, kind), -getattr(c, "priority", 0)))

    async def _is_available(self, c: Connector, kind: str | None = None) -> bool:
        if c.name not in self._avail:
            try:
                self._avail[c.name] = bool(await c.available())
            except Exception as e:  # noqa: BLE001
                self._avail[c.name] = False
                self._failed[c.name] = f"{type(e).__name__}: {e}"[:200]
        if not self._avail[c.name]:
            return False
        per_kind = getattr(c, "available_for", None)
        if per_kind is None or kind is None:
            return True
        key = f"{c.name}:{kind}"
        if key not in self._avail:
            # Not cached across calls: a CSV for this kind may be uploaded mid-case.
            return bool(await per_kind(kind))
        return self._avail[key]

    async def ladder(self, kind: str) -> list[LadderStep]:
        out = []
        for c in self.candidates(kind):
            ok = await self._is_available(c, kind)
            reason = "" if ok else self._failed.get(c.name) or _needs(c)
            out.append(LadderStep(c.name, _tier(c, kind), ok, reason))
        return out

    async def resolve(self, kind: str) -> Connector:
        for c in self.candidates(kind):
            if await self._is_available(c, kind):
                return c
        raise NoSource(kind, await self.ladder(kind))

    async def fetch(
        self, kind: str, window: Window | None, filters: dict[str, Any] | None = None
    ) -> EvidenceBundle:
        """Fetch from the best connector; on error, fall down the ladder to the next available one."""
        errors: list[LadderStep] = []
        for c in self.candidates(kind):
            if not await self._is_available(c, kind):
                errors.append(LadderStep(c.name, _tier(c, kind), False, _needs(c)))
                continue
            try:
                bundle = await c.fetch(kind, window, filters or {})
                if errors:
                    bundle.notes.append(
                        "fell back from: " + "; ".join(f"{e.connector} ({e.reason})" for e in errors)
                    )
                return bundle
            except NoSource:
                raise
            except Exception as e:  # noqa: BLE001 - fall down the ladder, record why
                errors.append(LadderStep(c.name, _tier(c, kind), True, f"{type(e).__name__}: {str(e)[:160]}"))
        raise NoSource(kind, errors)

    def get(self, name: str) -> Connector:
        for c in self.connectors:
            if c.name == name:
                return c
        raise KeyError(name)

    def find(self, method: str) -> Any:
        """First connector exposing a tool method (e.g. `compare`, `recording`, `flow_results`)."""
        for c in self.connectors:
            if hasattr(c, method) and self._avail.get(c.name, True):
                return getattr(c, method)
        raise NoSource(method, [])

    async def overview(self) -> list[dict[str, Any]]:
        rows = []
        for kind in KINDS:
            ladder = await self.ladder(kind)
            active = next((s for s in ladder if s.available), None)
            rows.append(
                {
                    "kind": kind,
                    "active": active.connector if active else None,
                    "active_tier": active.tier if active else None,
                    "active_tier_label": TIERS[active.tier][0] if active else None,
                    "ladder": [s.__dict__ for s in ladder],
                }
            )
        return rows


def _tier(c: Connector, kind: str) -> int:
    fn = getattr(c, "tier_for", None)
    return fn(kind) if fn else c.tier


def _needs(c: Connector) -> str:
    if getattr(c, "unavailable_reason", None):
        return c.unavailable_reason  # type: ignore[attr-defined]
    needs = getattr(c, "needs_env", ())
    return f"needs {', '.join(needs)}" if needs else "unavailable"
