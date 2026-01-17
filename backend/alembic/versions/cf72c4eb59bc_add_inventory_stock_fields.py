"""add inventory stock fields (current_qty, min_qty, location_label)

Revision ID: cf72c4eb59bc
Revises: b1c2d3e4f5a6
Create Date: 2026-01-17 06:59:23.766148

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cf72c4eb59bc'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add stock state fields to inventory_items
    op.add_column(
        'inventory_items',
        sa.Column('current_qty', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0')
    )
    op.add_column(
        'inventory_items',
        sa.Column('min_qty', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0')
    )
    op.add_column(
        'inventory_items',
        sa.Column('location_label', sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    # Remove stock state fields from inventory_items
    op.drop_column('inventory_items', 'location_label')
    op.drop_column('inventory_items', 'min_qty')
    op.drop_column('inventory_items', 'current_qty')
