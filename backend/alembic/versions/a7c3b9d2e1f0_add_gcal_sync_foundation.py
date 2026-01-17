"""add gcal sync foundation tables

Revision ID: a7c3b9d2e1f0
Revises: f9c1d2e3a4b5
Create Date: 2026-02-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a7c3b9d2e1f0"
down_revision = "f9c1d2e3a4b5"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
gcal_sync_mode_enum = sa.Enum("export", "import", "two_way", name="gcal_sync_mode")


def upgrade() -> None:
    op.create_table(
        "integrations_google_accounts",
        sa.Column("account_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("provider", sa.String(length=32), server_default="google", nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("token_scopes", sa.JSON(), server_default="[]", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_index(
        "ix_integrations_google_accounts_org_id",
        "integrations_google_accounts",
        ["org_id"],
    )

    op.create_table(
        "integrations_gcal_calendars",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("calendar_id", sa.Text(), nullable=False),
        sa.Column("mode", gcal_sync_mode_enum, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "calendar_id"),
    )
    op.create_index(
        "ix_integrations_gcal_calendars_org_id",
        "integrations_gcal_calendars",
        ["org_id"],
    )

    op.create_table(
        "integrations_gcal_sync_state",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("calendar_id", sa.Text(), nullable=False),
        sa.Column("sync_cursor", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "calendar_id"),
    )
    op.create_index(
        "ix_integrations_gcal_sync_state_org_id",
        "integrations_gcal_sync_state",
        ["org_id"],
    )

    op.create_table(
        "schedule_external_blocks",
        sa.Column("block_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("source", sa.String(length=32), server_default="gcal", nullable=False),
        sa.Column("external_event_id", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("block_id"),
        sa.UniqueConstraint(
            "org_id",
            "external_event_id",
            name="uq_schedule_external_blocks_org_event",
        ),
    )
    op.create_index(
        "ix_schedule_external_blocks_org_id",
        "schedule_external_blocks",
        ["org_id"],
    )

    op.create_table(
        "integrations_gcal_event_map",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("booking_id", sa.String(length=36), nullable=False),
        sa.Column("calendar_id", sa.Text(), nullable=False),
        sa.Column("external_event_id", sa.Text(), nullable=False),
        sa.Column("last_pushed_hash", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.booking_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "booking_id", "calendar_id"),
    )
    op.create_index(
        "ix_integrations_gcal_event_map_org_id",
        "integrations_gcal_event_map",
        ["org_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_integrations_gcal_event_map_org_id",
        table_name="integrations_gcal_event_map",
    )
    op.drop_table("integrations_gcal_event_map")
    op.drop_index(
        "ix_schedule_external_blocks_org_id",
        table_name="schedule_external_blocks",
    )
    op.drop_table("schedule_external_blocks")
    op.drop_index(
        "ix_integrations_gcal_sync_state_org_id",
        table_name="integrations_gcal_sync_state",
    )
    op.drop_table("integrations_gcal_sync_state")
    op.drop_index(
        "ix_integrations_gcal_calendars_org_id",
        table_name="integrations_gcal_calendars",
    )
    op.drop_table("integrations_gcal_calendars")
    op.drop_index(
        "ix_integrations_google_accounts_org_id",
        table_name="integrations_google_accounts",
    )
    op.drop_table("integrations_google_accounts")
