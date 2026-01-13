"""add archived_at to bookings

Revision ID: 0069_add_booking_archived_at
Revises: 0068_add_team_worker_archived_at
Create Date: 2026-02-16 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0069_add_booking_archived_at"
down_revision = "0068_add_team_worker_archived_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_bookings_archived_at", "bookings", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_bookings_archived_at", table_name="bookings")
    op.drop_column("bookings", "archived_at")
