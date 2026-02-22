"""add active-slot unique index for bookings

Revision ID: 0a1b2c3d4e5f
Revises: ff1a2b3c4d5e
Create Date: 2026-02-22 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0a1b2c3d4e5f"
down_revision = "ff1a2b3c4d5e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_bookings_active_slot",
        "bookings",
        ["org_id", "team_id", "starts_at"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'CONFIRMED')"),
        sqlite_where=sa.text("status IN ('PENDING', 'CONFIRMED')"),
    )


def downgrade() -> None:
    op.drop_index("uq_bookings_active_slot", table_name="bookings")
