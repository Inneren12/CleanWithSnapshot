"""merge heads 5d8c3a1b9e21 and 7a4c2d1f8e3b

Revision ID: 03149fcdd67f
Revises: 5d8c3a1b9e21, 7a4c2d1f8e3b
Create Date: 2026-01-17 03:50:51.101322

"""
from __future__ import annotations

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = "03149fcdd67f"
down_revision = ("5d8c3a1b9e21", "7a4c2d1f8e3b")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
