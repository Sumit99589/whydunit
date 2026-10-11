"""Blob storage in Postgres, for hosts without an S3 bucket and with an ephemeral disk

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE blobs (
            key          text PRIMARY KEY,
            data         bytea NOT NULL,
            content_type text NOT NULL DEFAULT 'application/octet-stream',
            created_at   timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE blobs")
