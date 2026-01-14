"""add booking address usage and defaults

Revision ID: 0080_booking_address_usage_and_address_defaults
Revises: 0079_chat_participant_keys_org_defaults
Create Date: 2025-10-06 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0080_booking_address_usage_and_address_defaults"
down_revision = "0079_chat_participant_keys_org_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("client_addresses") as batch_op:
        batch_op.alter_column("is_active", existing_type=sa.Boolean(), server_default=sa.true())

    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("address_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_bookings_address_id", ["address_id"])
        batch_op.create_foreign_key(
            "fk_bookings_address_id_client_addresses",
            "client_addresses",
            ["address_id"],
            ["address_id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_constraint("fk_bookings_address_id_client_addresses", type_="foreignkey")
        batch_op.drop_index("ix_bookings_address_id")
        batch_op.drop_column("address_id")

    with op.batch_alter_table("client_addresses") as batch_op:
        batch_op.alter_column(
            "is_active",
            existing_type=sa.Boolean(),
            server_default=sa.text("1"),
        )
