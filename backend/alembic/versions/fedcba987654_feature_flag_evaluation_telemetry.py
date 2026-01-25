"""add feature flag evaluation telemetry

Revision ID: fedcba987654
Revises: fe12a3b4c5d6
Create Date: 2026-03-15 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "fedcba987654"
down_revision = "fe12a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feature_flags",
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "feature_flags",
        sa.Column("evaluate_count", sa.BigInteger(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("feature_flags", "evaluate_count")
    op.drop_column("feature_flags", "last_evaluated_at")
