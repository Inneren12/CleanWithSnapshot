"""add postgres exclusion constraint for overlapping team bookings

Revision ID: 9d3e4f5a6b7c
Revises: 0a1b2c3d4e5f
Create Date: 2026-02-22 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "9d3e4f5a6b7c"
down_revision = "0a1b2c3d4e5f"
branch_labels = None
depends_on = None

EXCLUSION_CONSTRAINT_NAME = "bookings_team_time_no_overlap"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        f"""
        ALTER TABLE bookings
        ADD CONSTRAINT {EXCLUSION_CONSTRAINT_NAME}
        EXCLUDE USING gist (
            org_id WITH =,
            team_id WITH =,
            tstzrange(
                starts_at,
                starts_at + (duration_minutes * INTERVAL '1 minute'),
                '[)'
            ) WITH &&
        )
        WHERE (status IN ('PENDING', 'CONFIRMED') AND archived_at IS NULL)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        f"ALTER TABLE bookings DROP CONSTRAINT IF EXISTS {EXCLUSION_CONSTRAINT_NAME}"
    )
