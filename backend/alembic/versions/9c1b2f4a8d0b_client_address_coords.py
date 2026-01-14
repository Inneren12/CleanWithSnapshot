"""Add optional lat/lng to client addresses.

Revision ID: 9c1b2f4a8d0b
Revises: bc6a9a9f5c2b
Create Date: 2026-01-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "9c1b2f4a8d0b"
down_revision = "bc6a9a9f5c2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client_addresses", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("client_addresses", sa.Column("lng", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("client_addresses", "lng")
    op.drop_column("client_addresses", "lat")
