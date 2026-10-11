"""Tier 2: the long tail through PyAirbyte's open-source connectors.

One source is wired end to end: Stripe charges (`source-stripe`, stream `charges`) → payments. Adding another is
three steps: pick the source and stream from the PyAirbyte catalog, map its columns to the kind's schema in
SOURCES below, and list the env vars its config needs. PyAirbyte is an optional extra
(`uv sync --group airbyte`) because it installs connectors into their own virtualenvs.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from engine.connectors.base import BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame
from engine.settings import env


def _stripe_charge(r: dict[str, Any]) -> dict[str, Any]:
    outcome = r.get("outcome") or {}
    card = (r.get("payment_method_details") or {}).get("card") or {}
    created = r.get("created")
    return {
        "id": r.get("id"),
        "created": datetime.fromtimestamp(created, tz=UTC) if isinstance(created, int | float) else created,
        "amount": r.get("amount"),
        "currency": r.get("currency"),
        "status": r.get("status"),
        "outcome_type": outcome.get("type"),
        "decline_code": r.get("failure_code") or outcome.get("reason"),
        "card_brand": card.get("brand"),
        "card_country": card.get("country"),
        "country": (r.get("metadata") or {}).get("country"),
    }


SOURCES = {
    "payments": {
        "source": "source-stripe",
        "stream": "charges",
        "env": ["STRIPE_SECRET_KEY"],
        "config": lambda w: {
            "client_secret": env("STRIPE_SECRET_KEY"),
            "account_id": env("STRIPE_ACCOUNT_ID", ""),
            "start_date": (w.start if w else datetime(2026, 1, 1, tzinfo=UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "row": _stripe_charge,
    },
}


class PyAirbyte(BaseConnector):
    name = "pyairbyte"
    tier = 2
    kinds = tuple(SOURCES)
    unavailable_reason = "PyAirbyte not installed (uv sync --group airbyte) or source credentials missing"

    def __init__(self, ab: Any = None):
        self._ab = ab

    def _module(self) -> Any:
        if self._ab is None:
            import airbyte  # optional dependency

            self._ab = airbyte
        return self._ab

    async def available(self) -> bool:
        try:
            self._module()
        except ImportError:
            return False
        return all(env(v) for s in SOURCES.values() for v in s["env"])

    async def fetch(
        self, kind: str, window: Window | None, filters: dict[str, Any] | None = None
    ) -> EvidenceBundle:
        spec = SOURCES[kind]
        ab = self._module()

        def read() -> list[dict[str, Any]]:
            source = ab.get_source(
                spec["source"],
                config=spec["config"](window),
                streams=[spec["stream"]],
                install_if_missing=True,
            )
            result = source.read()
            return [dict(r) for r in result[spec["stream"]]]

        raw = await asyncio.to_thread(read)
        rows = [spec["row"](r) for r in raw]
        if window:
            rows = [r for r in rows if r["created"] and window.start <= r["created"] < window.end]
        df = frame(rows, kind)
        return make_bundle(
            kind,
            self,
            df,
            window,
            query={"source": spec["source"], "stream": spec["stream"]},
            summary=f"{df.height:,} {kind} rows via PyAirbyte {spec['source']}/{spec['stream']}, "
            f"{fmt_window(window)}",
            data_ref={"source": f"pyairbyte:{spec['source']}"},
        )
