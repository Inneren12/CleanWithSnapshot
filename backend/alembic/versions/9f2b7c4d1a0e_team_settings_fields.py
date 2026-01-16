"""Add team settings fields.

Revision ID: 9f2b7c4d1a0e
Revises: 9c1b2f4a8d0b
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "9f2b7c4d1a0e"
down_revision = "9c1b2f4a8d0b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "teams",
        sa.Column("lead_worker_id", sa.Integer(), sa.ForeignKey("workers.worker_id"), nullable=True),
    )
    op.add_column(
        "teams",
        sa.Column("zones", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "teams",
        sa.Column("specializations", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column("teams", sa.Column("calendar_color", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("teams", "calendar_color")
    op.drop_column("teams", "specializations")
    op.drop_column("teams", "zones")
    op.drop_column("teams", "lead_worker_id")
