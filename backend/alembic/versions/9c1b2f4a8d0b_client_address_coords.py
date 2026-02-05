"""Add optional lat/lng to client addresses.

Revision ID: 9c1b2f4a8d0b
Revises: 0077_client_addresses
Create Date: 2026-01-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "9c1b2f4a8d0b"
down_revision = "0077_client_addresses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client_addresses", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("client_addresses", sa.Column("lng", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("client_addresses", "lng")
    op.drop_column("client_addresses", "lat")
