"""cleanup broken migration state

Revision ID: 0092_cleanup_broken_migration
Revises: 0091_merge_all_heads
Create Date: 2026-01-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0092_cleanup_broken_migration"
down_revision = "0091_merge_all_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove broken migration record if it exists
    op.execute(sa.text("DELETE FROM alembic_version WHERE version_num = 'a1b2c3d4e5f6'"))

    # Drop tables if they were partially created
    op.execute(sa.text("DROP TABLE IF EXISTS inventory_items CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS inventory_categories CASCADE"))


def downgrade() -> None:
    pass
