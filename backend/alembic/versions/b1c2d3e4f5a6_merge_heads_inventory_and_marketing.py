"""merge heads a1b2c3d4e5f6 (inventory) and aa12b3cd45ef (marketing)

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6, aa12b3cd45ef
Create Date: 2026-01-17 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a6"
down_revision = ("a1b2c3d4e5f6", "aa12b3cd45ef")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op merge migration
    pass


def downgrade() -> None:
    # No-op merge migration
    pass
