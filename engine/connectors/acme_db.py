"""Acme's own application tables: helpdesk tickets and reviews (tier 1, Acme's system of record), and its
payment-attempt log (tier 2, a warehouse-style fallback when the Stripe API is not connected)."""

from __future__ import annotations

from typing import Any

from engine import db
from engine.connectors.base import BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame, top_counts


async def _db_ok() -> bool:
    try:
        await db.fetchrow("SELECT 1 FROM acme.helpdesk_tickets LIMIT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


def _window_sql(col: str, window: Window | None) -> tuple[str, list[Any]]:
    return (f" WHERE {col} >= %s AND {col} < %s", [window.start, window.end]) if window else ("", [])


class Helpdesk(BaseConnector):
    name = "acme_helpdesk"
    tier = 1
    kinds = ("support_tickets",)

    async def available(self) -> bool:
        return await _db_ok()

    async def _fetch_support_tickets(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        w, p = _window_sql("created_at", window)
        rows = await db.fetch(
            f"SELECT id, created_at, subject, body, channel, meta FROM acme.helpdesk_tickets{w} "
            "ORDER BY created_at",
            p,
        )
        df = frame(rows, "support_tickets")
        return make_bundle(
            "support_tickets",
            self,
            df,
            window,
            summary=f"{df.height:,} support tickets in Acme's helpdesk, {fmt_window(window)}",
            data_ref={"source": "postgres:acme.helpdesk_tickets"},
        )


class Reviews(BaseConnector):
    name = "acme_reviews"
    tier = 1
    kinds = ("reviews",)

    async def available(self) -> bool:
        return await _db_ok()

    async def _fetch_reviews(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        w, p = _window_sql("created_at", window)
        rows = await db.fetch(
            f"SELECT id, created_at, platform, rating, title, body FROM acme.reviews{w} ORDER BY created_at",
            p,
        )
        df = frame(rows, "reviews")
        avg = f", average rating {df['rating'].mean():.1f}" if df.height else ""
        return make_bundle(
            "reviews",
            self,
            df,
            window,
            summary=f"{df.height:,} app reviews, {fmt_window(window)}{avg}",
            data_ref={"source": "postgres:acme.reviews"},
        )


class AcmePaymentLog(BaseConnector):
    name = "acme_payment_log"
    tier = 2
    kinds = ("payments",)

    async def available(self) -> bool:
        return await _db_ok()

    async def _fetch_payments(self, window: Window | None, filters: dict[str, Any]) -> EvidenceBundle:
        w, p = _window_sql("created_at", window)
        rows = await db.fetch(
            f"""SELECT id, created_at AS created, amount_cents AS amount, currency,
                       CASE WHEN outcome = 'succeeded' THEN 'succeeded' ELSE 'requires_payment_method' END AS status,
                       CASE outcome WHEN 'succeeded' THEN 'authorized' WHEN 'declined' THEN 'issuer_declined'
                                    ELSE 'api_error' END AS outcome_type,
                       decline_code, card_brand, card_country, card_country AS country, provider
                FROM acme.payment_attempts{w} ORDER BY created_at""",
            p,
        )
        df = frame(rows, "payments")
        summary = f"{df.height:,} payment attempts from Acme's payment log, {fmt_window(window)}" + (
            f": {top_counts(df['outcome_type'].to_list())}" if df.height else ""
        )
        return make_bundle(
            "payments",
            self,
            df,
            window,
            summary=summary,
            data_ref={"source": "postgres:acme.payment_attempts"},
        )
