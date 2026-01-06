"""Add stripe_events_processed table

Revision ID: 0052_stripe_events_processed
Revises: 0051_job_runner_id
Create Date: 2025-03-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0052_stripe_events_processed"
down_revision: Union[str, None] = "0051_job_runner_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stripe_events_processed",
        sa.Column("event_id", sa.String(length=255), primary_key=True),
        sa.Column("event_type", sa.String(length=128), nullable=True),
        sa.Column("livemode", sa.Boolean(), nullable=True),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_stripe_events_processed_request_id",
        "stripe_events_processed",
        ["request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_stripe_events_processed_request_id", table_name="stripe_events_processed")
    op.drop_table("stripe_events_processed")
