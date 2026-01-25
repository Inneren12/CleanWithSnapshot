"""add feature flag pinned flag

Revision ID: 1a2b3c4d5e6f
Revises: fedcba987654
Create Date: 2026-03-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "1a2b3c4d5e6f"
down_revision = "fedcba987654"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feature_flags",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("feature_flags", "pinned")
