"""add client_users is_active

Revision ID: 2c3b4b9a1e9a
Revises: f8dba77650d4
Create Date: 2025-05-22 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "2c3b4b9a1e9a"
down_revision = "f8dba77650d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )


def downgrade() -> None:
    op.drop_column("client_users", "is_active")
