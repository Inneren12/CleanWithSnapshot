"""add finance_ready to organization settings

Revision ID: a2b3c4d5e6f7
Revises: f9c1d2e3a4b5
Create Date: 2026-02-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "f9c1d2e3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organization_settings",
        sa.Column("finance_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("organization_settings", "finance_ready")
