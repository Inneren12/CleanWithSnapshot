"""add org storage quota

Revision ID: fb1c2d3e4f5c
Revises: fa0c1d2e3f4b
Create Date: 2026-02-21 00:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "fb1c2d3e4f5c"
down_revision = "fa0c1d2e3f4b"
branch_labels = None
depends_on = None


UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.add_column("organization_settings", sa.Column("max_storage_bytes", sa.BigInteger(), nullable=True))
    op.add_column(
        "organization_settings",
        sa.Column("storage_bytes_used", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "org_storage_reservations",
        sa.Column("reservation_id", UUID_TYPE, primary_key=True, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("bytes_reserved", sa.BigInteger(), nullable=False),
        sa.Column("bytes_finalized", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_storage_reservations_org", "org_storage_reservations", ["org_id"])
    op.create_index(
        "ix_storage_reservations_org_status",
        "org_storage_reservations",
        ["org_id", "status"],
    )
    op.create_index("ix_storage_reservations_expires", "org_storage_reservations", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_storage_reservations_expires", table_name="org_storage_reservations")
    op.drop_index("ix_storage_reservations_org_status", table_name="org_storage_reservations")
    op.drop_index("ix_storage_reservations_org", table_name="org_storage_reservations")
    op.drop_table("org_storage_reservations")
    op.drop_column("organization_settings", "storage_bytes_used")
    op.drop_column("organization_settings", "max_storage_bytes")
