"""add worker skills and ratings

Revision ID: 0070_add_worker_skills_and_ratings
Revises: 0069_add_booking_archived_at
Create Date: 2025-05-15 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0070_add_worker_skills_and_ratings"
down_revision = "0069_add_booking_archived_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workers") as batch_op:
        batch_op.add_column(sa.Column("skills", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("rating_avg", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("workers") as batch_op:
        batch_op.drop_column("rating_count")
        batch_op.drop_column("rating_avg")
        batch_op.drop_column("skills")
