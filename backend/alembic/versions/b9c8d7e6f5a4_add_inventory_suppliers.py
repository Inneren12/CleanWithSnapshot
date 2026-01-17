"""add inventory suppliers table

Revision ID: b9c8d7e6f5a4
Revises: a9a9247301a9
Create Date: 2026-02-10 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

# revision identifiers, used by Alembic.
revision = "b9c8d7e6f5a4"
down_revision = "a9a9247301a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_suppliers",
        sa.Column("supplier_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("delivery_days", sa.String(length=100), nullable=True),
        sa.Column("min_order_cents", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.org_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("supplier_id"),
    )
    op.create_index(
        "ix_inventory_suppliers_org_id",
        "inventory_suppliers",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_suppliers_org_name",
        "inventory_suppliers",
        ["org_id", "name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_suppliers_org_name", table_name="inventory_suppliers")
    op.drop_index("ix_inventory_suppliers_org_id", table_name="inventory_suppliers")
    op.drop_table("inventory_suppliers")
