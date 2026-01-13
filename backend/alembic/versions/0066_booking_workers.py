"""add booking_workers join table

Revision ID: 0066
Revises: 6565fde00428
Create Date: 2026-01-13 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0066"
down_revision = "6565fde00428"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "booking_workers",
        sa.Column(
            "booking_id",
            sa.String(length=36),
            sa.ForeignKey("bookings.booking_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.worker_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("role", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_booking_workers_booking_id", "booking_workers", ["booking_id"])
    op.create_index("ix_booking_workers_worker_id", "booking_workers", ["worker_id"])


def downgrade() -> None:
    op.drop_index("ix_booking_workers_worker_id", table_name="booking_workers")
    op.drop_index("ix_booking_workers_booking_id", table_name="booking_workers")
    op.drop_table("booking_workers")
