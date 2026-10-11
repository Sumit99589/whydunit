from alembic import context
from sqlalchemy import create_engine, pool

from engine.db import sqlalchemy_url

config = context.config


def run_migrations_online() -> None:
    url = config.attributes.get("url") or sqlalchemy_url()
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
