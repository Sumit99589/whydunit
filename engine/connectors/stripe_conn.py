"""Tier 1: Stripe (test mode) PaymentIntents with outcomes, decline codes and card country."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from engine.connectors.base import BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame, top_counts
from engine.settings import env


def _get(obj: Any, *path: str) -> Any:
    for p in path:
        if obj is None:
            return None
        obj = obj.get(p) if isinstance(obj, dict) else getattr(obj, p, None)
    return obj


def payment_row(pi: dict[str, Any]) -> dict[str, Any]:
    charge = pi.get("latest_charge") if isinstance(pi.get("latest_charge"), dict) else None
    err = pi.get("last_payment_error") or {}
    card = _get(charge, "payment_method_details", "card") or {}
    outcome_type = _get(charge, "outcome", "type")
    decline = (
        (err.get("decline_code") or _get(charge, "outcome", "reason"))
        if pi.get("status") != "succeeded"
        else None
    )
    if not outcome_type:
        outcome_type = (
            "authorized"
            if pi.get("status") == "succeeded"
            else "issuer_declined"
            if err.get("type") == "card_error"
            else "api_error"
        )
    return {
        "id": pi["id"],
        "created": datetime.fromtimestamp(pi["created"], tz=UTC),
        "amount": pi["amount"],
        "currency": pi["currency"],
        "status": pi["status"],
        "outcome_type": outcome_type,
        "decline_code": decline,
        "card_brand": card.get("brand") or _get(err, "payment_method", "card", "brand"),
        "card_country": card.get("country") or _get(err, "payment_method", "card", "country"),
        "country": (pi.get("metadata") or {}).get("country") or None,
        "synthetic": (pi.get("metadata") or {}).get("synthetic") == "true",
    }


class Stripe(BaseConnector):
    name = "stripe"
    tier = 1
    kinds = ("payments",)
    needs_env = ("STRIPE_SECRET_KEY",)

    def __init__(self, client: Any = None):
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import stripe

            key = env("STRIPE_SECRET_KEY") or ""
            if not key.startswith(("sk_test_", "rk_test_")):
                raise RuntimeError("Whydunit only reads Stripe in test mode")
            self._client = stripe.StripeClient(key)
        return self._client

    def _list(self, window: Window | None, limit: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": 100, "expand": ["data.latest_charge"]}
        if window:
            params["created"] = {"gte": int(window.start.timestamp()), "lt": int(window.end.timestamp())}
        out = []
        for pi in self.client.v1.payment_intents.list(params=params).auto_paging_iter():
            out.append(pi.to_dict() if hasattr(pi, "to_dict") else dict(pi))
            if len(out) >= limit:
                break
        return out

    async def _fetch_payments(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        pis = await asyncio.to_thread(self._list, window, int(filters.get("limit", 20000)))
        df = frame([payment_row(p) for p in pis], "payments")
        summary = f"{df.height:,} Stripe PaymentIntents (test mode), {fmt_window(window)}" + (
            f": {top_counts(df['outcome_type'].to_list())}" if df.height else ""
        )
        return make_bundle(
            "payments",
            self,
            df,
            window,
            summary=summary,
            data_ref={"source": "stripe:/v1/payment_intents", "mode": "test"},
        )
