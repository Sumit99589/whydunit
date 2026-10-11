"""CSV uploads (tier 3) and evidence requests to a human (tier 6)

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE uploads (
            id          text PRIMARY KEY,
            kind        text NOT NULL,
            filename    text NOT NULL,
            blob_key    text NOT NULL,
            status      text NOT NULL DEFAULT 'pending',
            columns     jsonb NOT NULL DEFAULT '[]'::jsonb,
            mapping     jsonb NOT NULL DEFAULT '{}'::jsonb,
            mapped_by   text,
            preview     jsonb NOT NULL DEFAULT '[]'::jsonb,
            row_count   integer NOT NULL DEFAULT 0,
            case_id     text,
            created_at  timestamptz NOT NULL DEFAULT now(),
            confirmed_at timestamptz
        );
        CREATE TABLE evidence_requests (
            id          text PRIMARY KEY,
            case_id     text NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            kind        text NOT NULL,
            detective   text,
            reason      text NOT NULL,
            status      text NOT NULL DEFAULT 'open',
            upload_id   text,
            created_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (case_id, kind)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE evidence_requests; DROP TABLE uploads;")
