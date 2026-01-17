"""add inventory consumption

Revision ID: c4d5e6f7a8b9
Revises: b2f3c4d5e6f7
Create Date: 2026-02-20 00:00:00.000000
"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "b2f3c4d5e6f7"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.create_table(
        "inventory_consumption",
        sa.Column("consumption_id", UUID_TYPE, primary_key=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column(
            "booking_id",
            sa.String(length=36),
            sa.ForeignKey("bookings.booking_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "service_type_id",
            sa.Integer(),
            sa.ForeignKey("service_types.service_type_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            UUID_TYPE,
            sa.ForeignKey("inventory_items.item_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("qty", sa.Numeric(10, 2), nullable=False),
        sa.Column("unit_cost_cents", sa.Integer(), nullable=False),
        sa.Column("total_cost_cents", sa.Integer(), nullable=False),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("recorded_by", sa.String(length=255), nullable=False),
    )
    op.create_index("ix_inventory_consumption_org_id", "inventory_consumption", ["org_id"])
    op.create_index(
        "ix_inventory_consumption_booking",
        "inventory_consumption",
        ["org_id", "booking_id"],
    )
    op.create_index(
        "ix_inventory_consumption_service_type",
        "inventory_consumption",
        ["org_id", "service_type_id"],
    )
    op.create_index(
        "ix_inventory_consumption_item",
        "inventory_consumption",
        ["org_id", "item_id"],
    )
    op.create_index(
        "ix_inventory_consumption_consumed_at",
        "inventory_consumption",
        ["org_id", "consumed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_consumption_consumed_at", table_name="inventory_consumption")
    op.drop_index("ix_inventory_consumption_item", table_name="inventory_consumption")
    op.drop_index("ix_inventory_consumption_service_type", table_name="inventory_consumption")
    op.drop_index("ix_inventory_consumption_booking", table_name="inventory_consumption")
    op.drop_index("ix_inventory_consumption_org_id", table_name="inventory_consumption")
    op.drop_table("inventory_consumption")
