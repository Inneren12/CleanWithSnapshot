"""add inventory categories and items tables

Revision ID: a1b2c3d4e5f6
Revises: f0b1c2d3e4f5
Create Date: 2026-01-17 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create inventory_categories table
    op.create_table(
        "inventory_categories",
        sa.Column("category_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
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
        sa.PrimaryKeyConstraint("category_id"),
    )
    op.create_index(
        "ix_inventory_categories_org_id",
        "inventory_categories",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_categories_org_sort",
        "inventory_categories",
        ["org_id", "sort_order"],
        unique=False,
    )

    # Create inventory_items table
    op.create_table(
        "inventory_items",
        sa.Column("item_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("category_id", UUID_TYPE, nullable=True),
        sa.Column("sku", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
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
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["inventory_categories.category_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_index(
        "ix_inventory_items_category_id",
        "inventory_items",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_items_org_id",
        "inventory_items",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_items_org_name",
        "inventory_items",
        ["org_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_items_org_active",
        "inventory_items",
        ["org_id", "active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_items_org_active", table_name="inventory_items")
    op.drop_index("ix_inventory_items_org_name", table_name="inventory_items")
    op.drop_index("ix_inventory_items_org_id", table_name="inventory_items")
    op.drop_index("ix_inventory_items_category_id", table_name="inventory_items")
    op.drop_table("inventory_items")

    op.drop_index("ix_inventory_categories_org_sort", table_name="inventory_categories")
    op.drop_index("ix_inventory_categories_org_id", table_name="inventory_categories")
    op.drop_table("inventory_categories")
