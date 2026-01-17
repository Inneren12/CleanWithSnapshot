"""merge heads a1b2c3d4e5f6 b1c2d3e4f5a6 cf72c4eb59bc f1e2d3c4b5a6

Revision ID: a9a9247301a9
Revises: f1e2d3c4b5a6
Create Date: 2026-01-17 08:14:57.413908

"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = "a9a9247301a9"
down_revision = "f1e2d3c4b5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
