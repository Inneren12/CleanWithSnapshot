"""add purchase orders

Revision ID: b2f3c4d5e6f7
Revises: a9a9247301a9, b9c8d7e6f5a4
Create Date: 2026-01-20 12:10:00.000000

"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

revision = "b2f3c4d5e6f7"
down_revision = ("a9a9247301a9", "b9c8d7e6f5a4")
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("po_id", UUID_TYPE, primary_key=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column(
            "supplier_id",
            UUID_TYPE,
            sa.ForeignKey("inventory_suppliers.supplier_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("ordered_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("subtotal_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tax_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("shipping_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_purchase_orders_org_id", "purchase_orders", ["org_id"])
    op.create_index("ix_purchase_orders_org_status", "purchase_orders", ["org_id", "status"])
    op.create_index(
        "ix_purchase_orders_org_supplier",
        "purchase_orders",
        ["org_id", "supplier_id"],
    )

    op.create_table(
        "purchase_order_items",
        sa.Column("po_item_id", UUID_TYPE, primary_key=True),
        sa.Column(
            "po_id",
            UUID_TYPE,
            sa.ForeignKey("purchase_orders.po_id", ondelete="CASCADE"),
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
        sa.Column("line_total_cents", sa.Integer(), nullable=False),
    )
    op.create_index("ix_purchase_order_items_po_id", "purchase_order_items", ["po_id"])
    op.create_index("ix_purchase_order_items_item_id", "purchase_order_items", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_purchase_order_items_item_id", table_name="purchase_order_items")
    op.drop_index("ix_purchase_order_items_po_id", table_name="purchase_order_items")
    op.drop_table("purchase_order_items")

    op.drop_index("ix_purchase_orders_org_supplier", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_org_status", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_org_id", table_name="purchase_orders")
    op.drop_table("purchase_orders")
