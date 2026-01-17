"""add position to quality issue tags

Revision ID: 1b2c3d4e5f6a
Revises: 9b7c1d2e3f4a
Create Date: 2026-01-22 10:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "1b2c3d4e5f6a"
down_revision = "9b7c1d2e3f4a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("quality_issue_tags") as batch_op:
        batch_op.add_column(sa.Column("position", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_quality_issue_tags_issue_id_position",
            ["issue_id", "position"],
        )


def downgrade() -> None:
    with op.batch_alter_table("quality_issue_tags") as batch_op:
        batch_op.drop_index("ix_quality_issue_tags_issue_id_position")
        batch_op.drop_column("position")
