"""add client addresses

Revision ID: 0077_client_addresses
Revises: 0076_client_note_type
Create Date: 2025-10-06 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0077_client_addresses"
down_revision = "0076_client_note_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_addresses",
        sa.Column("address_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("address_text", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint([
            "org_id"], ["organizations.org_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint([
            "client_id"], ["client_users.client_id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_client_addresses_org_client",
        "client_addresses",
        ["org_id", "client_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_client_addresses_org_client", table_name="client_addresses")
    op.drop_table("client_addresses")
