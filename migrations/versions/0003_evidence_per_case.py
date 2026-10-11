"""evidence ids are deterministic per query, so key evidence by (case_id, id)

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE evidence DROP CONSTRAINT evidence_pkey;
        ALTER TABLE evidence ADD PRIMARY KEY (case_id, id);
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE evidence DROP CONSTRAINT evidence_pkey;
        ALTER TABLE evidence ADD PRIMARY KEY (id);
    """)
