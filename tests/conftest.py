import os

import pytest

from engine import db

TEST_DB = "whydunit_test"


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
