"""Connector ladder. `registry_for("live")` or `registry_for("fixture:3inc")`."""

from __future__ import annotations

from engine.connectors.registry import NoSource, Registry

__all__ = ["NoSource", "Registry", "live_registry", "fixture_registry", "registry_for"]


def live_registry() -> Registry:
    from engine.connectors.acme_db import AcmePaymentLog, Helpdesk, Reviews
    from engine.connectors.github import GitHub
    from engine.connectors.google_ads import GoogleAds
    from engine.connectors.holidays import Holidays
    from engine.connectors.mock_ads import MockAds
    from engine.connectors.replays import Replays
    from engine.connectors.statuspages import StatusPages
    from engine.connectors.stripe_conn import Stripe
    from engine.connectors.tavily_conn import Tavily
    from engine.connectors.vercel import Vercel
    from engine.connectors.whydunit_events import WhydunitEvents

    return Registry(
        [
            WhydunitEvents(),
            Replays(),
            Vercel(),
            GitHub(),
            Stripe(),
            AcmePaymentLog(),
            GoogleAds(),
            MockAds(),
            Helpdesk(),
            Reviews(),
            Tavily(),
            Holidays(),
            StatusPages(),
        ],
        mode="live",
        label="Live Acme",
    )


def fixture_registry(world: str) -> Registry:
    from engine.connectors.fixture import FixtureWorld
    from engine.fixtures.world import resolve_world

    path = resolve_world(world)
    return Registry([FixtureWorld(path)], mode="fixture", label=f"Fixture world {path.stem}")


def registry_for(world: str) -> Registry:
    return live_registry() if world in ("live", "live:acme") else fixture_registry(world)
