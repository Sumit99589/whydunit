"""Connector ladder. `registry_for("live")` or `registry_for("fixture:3inc")`."""

from __future__ import annotations

from engine.connectors.registry import NoSource, Registry

__all__ = ["NoSource", "Registry", "live_registry", "fixture_registry", "registry_for"]


def live_registry() -> Registry:
    from engine.connectors.acme_db import AcmePaymentLog, Helpdesk, Reviews
    from engine.connectors.airbyte_conn import PyAirbyte
    from engine.connectors.csv_upload import CSVUpload
    from engine.connectors.github import GitHub
    from engine.connectors.google_ads import GoogleAds
    from engine.connectors.holidays import Holidays
    from engine.connectors.mock_ads import MockAds
    from engine.connectors.replays import Replays
    from engine.connectors.screen_reader import ScreenReader
    from engine.connectors.statuspages import StatusPages
    from engine.connectors.stripe_conn import Stripe
    from engine.connectors.tavily_conn import Tavily
    from engine.connectors.vercel import Vercel
    from engine.connectors.warehouse import Warehouse
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
            Warehouse(),
            PyAirbyte(),
            CSVUpload(),
            ScreenReader(),
        ],
        mode="live",
        label="Live Acme",
    )


def fixture_registry(world: str) -> Registry:
    from engine.connectors.fixture import FixtureWorld
    from engine.connectors.tavily_conn import Tavily
    from engine.fixtures.world import resolve_world

    path = resolve_world(world)
    # The fixture world answers every kind (deterministic); Tavily rides along so the Voice detective can make one
    # real, harmless public-web search ("is anyone talking about Acme Notes?") when a key is configured.
    return Registry([FixtureWorld(path), Tavily()], mode="fixture", label=f"Fixture world {path.stem}")


def registry_for(world: str) -> Registry:
    return live_registry() if world in ("live", "live:acme") else fixture_registry(world)
