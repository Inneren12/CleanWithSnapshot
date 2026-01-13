"""Add cascade delete for event_logs booking FK.

Revision ID: 0067
Revises: 0066
Create Date: 2026-01-13 12:30:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("event_logs_booking_id_fkey", "event_logs", type_="foreignkey")
    op.create_foreign_key(
        "event_logs_booking_id_fkey",
        "event_logs",
        "bookings",
        ["booking_id"],
        ["booking_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("event_logs_booking_id_fkey", "event_logs", type_="foreignkey")
    op.create_foreign_key(
        "event_logs_booking_id_fkey",
        "event_logs",
        "bookings",
        ["booking_id"],
        ["booking_id"],
    )
