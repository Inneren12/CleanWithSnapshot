"""add client feedback

Revision ID: 0078_client_feedback
Revises: 0077_client_addresses
Create Date: 2025-10-06 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0078_client_feedback"
down_revision = "0077_client_addresses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_feedback",
        sa.Column("feedback_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("booking_id", sa.String(length=36), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["client_id"], ["client_users.client_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.booking_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "booking_id", name="uq_client_feedback_org_booking"),
    )
    op.create_index(
        "ix_client_feedback_org_client_created",
        "client_feedback",
        ["org_id", "client_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_client_feedback_org_client_created", table_name="client_feedback")
    op.drop_table("client_feedback")
