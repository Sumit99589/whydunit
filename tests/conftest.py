import os

import pytest

from engine import db

TEST_DB = "whydunit_test"

# engine.settings loads .env at import; tests must never reach the real systems those values point at
# (a run once merged the planted incident branch in the live acme-demo repo).
REAL_SYSTEM_ENV = (
    "DATABASE_URL",
    "ACME_URL",
    "ACME_GITHUB_TOKEN",
    "GITHUB_TOKEN",
    "WHYDUNIT_GITHUB_TOKEN",
    "GITHUB_TOKEN_WHYDUNIT",
    "VERCEL_TOKEN",
    "VERCEL_TEAM_ID",
    "WHYDUNIT_ENGINE_URL",
    "WHYDUNIT_ADMIN_KEY",
    "WHYDUNIT_INGEST_KEY",
    "NEBIUS_API_KEY",
    "NEBIUS_PROJECT_ID",
    "TAVILY_API_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "S3_ENDPOINT_URL",
    "S3_BUCKET",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "NEON_API_KEY",
    "HF_TOKEN",
    "WATCHER_WEBHOOK_URL",
    "FLAGSHIP_CASE_ID",
)


@pytest.fixture(autouse=True)
def _no_real_systems(monkeypatch):
    for name in REAL_SYSTEM_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def database_url():
    """A freshly migrated test database: embedded Postgres locally, TEST_DATABASE_URL in CI if set."""
    import psycopg
    from alembic import command
    from alembic.config import Config

    from engine.settings import ROOT

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        admin = db._embedded_url("postgres")
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {TEST_DB}")
        url = db._embedded_url(TEST_DB)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["url"] = db.sqlalchemy_url(url)
    command.upgrade(cfg, "head")
    return url


@pytest.fixture
async def pg(database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    await db.close_pool()
    yield db
    await db.close_pool()
