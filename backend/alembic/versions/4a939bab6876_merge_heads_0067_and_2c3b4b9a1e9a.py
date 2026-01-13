"""merge heads 0067 and 2c3b4b9a1e9a

Revision ID: 4a939bab6876
Revises: 0067, 2c3b4b9a1e9a
Create Date: 2026-01-13 22:56:34.287525

"""
from __future__ import annotations

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = "4a939bab6876"
down_revision = ("0067", "2c3b4b9a1e9a")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
