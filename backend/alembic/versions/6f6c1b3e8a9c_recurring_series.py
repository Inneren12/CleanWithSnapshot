"""add recurring series table

Revision ID: 6f6c1b3e8a9c
Revises: 0018_subscriptions, 0025_admin_audit_logs, b8e1c2d3f4a5, f83f22a8223b
Create Date: 2025-09-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6f6c1b3e8a9c"
down_revision = ("0018_subscriptions", "0025_admin_audit_logs", "b8e1c2d3f4a5", "f83f22a8223b")
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "recurring_series",
        sa.Column("series_id", UUID_TYPE, primary_key=True, nullable=False),
        sa.Column("org_id", UUID_TYPE, sa.ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(36), sa.ForeignKey("client_users.client_id", ondelete="SET NULL")),
        sa.Column(
            "address_id",
            sa.Integer,
            sa.ForeignKey("client_addresses.address_id", ondelete="SET NULL"),
        ),
        sa.Column(
            "service_type_id",
            sa.Integer,
            sa.ForeignKey("service_types.service_type_id", ondelete="SET NULL"),
        ),
        sa.Column("preferred_team_id", sa.Integer, sa.ForeignKey("teams.team_id", ondelete="SET NULL")),
        sa.Column("preferred_worker_id", sa.Integer, sa.ForeignKey("workers.worker_id", ondelete="SET NULL")),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="weekly"),
        sa.Column("interval", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("by_weekday", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("by_monthday", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("ends_on", sa.Date()),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="180"),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_recurring_series_org_id", "recurring_series", ["org_id"])
    op.create_index("ix_recurring_series_status", "recurring_series", ["status"])
    op.create_index("ix_recurring_series_next_run", "recurring_series", ["next_run_at"])

    op.add_column(
        "bookings",
        sa.Column("recurring_series_id", UUID_TYPE, sa.ForeignKey("recurring_series.series_id", ondelete="SET NULL")),
    )
    op.create_index("ix_bookings_recurring_series_id", "bookings", ["recurring_series_id"])
    op.create_unique_constraint(
        "uq_bookings_recurring_start",
        "bookings",
        ["recurring_series_id", "starts_at"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_bookings_recurring_start", "bookings", type_="unique")
    op.drop_index("ix_bookings_recurring_series_id", table_name="bookings")
    op.drop_column("bookings", "recurring_series_id")

    op.drop_index("ix_recurring_series_next_run", table_name="recurring_series")
    op.drop_index("ix_recurring_series_status", table_name="recurring_series")
    op.drop_index("ix_recurring_series_org_id", table_name="recurring_series")
    op.drop_table("recurring_series")
