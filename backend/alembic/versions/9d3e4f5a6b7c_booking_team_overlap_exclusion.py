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
FUNCTION_NAME = "bookings_add_minutes"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # Define an IMMUTABLE function to wrap the time addition.
    # Postgres considers 'timestamptz + interval' STABLE (not IMMUTABLE) because
    # intervals like '1 day' can vary based on timezone (DST).
    # However, adding minutes is deterministic for UTC timestamps, so we mark it IMMUTABLE.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {FUNCTION_NAME}(ts timestamptz, mins integer)
        RETURNS timestamptz LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
        $$ SELECT ts + (mins * INTERVAL '1 minute') $$;
        """
    )

    op.execute(
        f"""
        ALTER TABLE bookings
        ADD CONSTRAINT {EXCLUSION_CONSTRAINT_NAME}
        EXCLUDE USING gist (
            org_id WITH =,
            team_id WITH =,
            tstzrange(
                starts_at,
                {FUNCTION_NAME}(starts_at, duration_minutes),
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
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}(timestamptz, integer)")
