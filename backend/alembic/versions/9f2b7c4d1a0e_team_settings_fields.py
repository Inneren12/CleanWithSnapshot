"""Add team settings fields.

Revision ID: 9f2b7c4d1a0e
Revises: 9c1b2f4a8d0b
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "9f2b7c4d1a0e"
down_revision = "9c1b2f4a8d0b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("teams") as batch_op:
        batch_op.add_column(
            sa.Column(
                "lead_worker_id",
                sa.Integer(),
                sa.ForeignKey("workers.worker_id", name="fk_teams_lead_worker_id"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("zones", sa.JSON(), server_default=sa.text("'[]'"), nullable=False)
        )
        batch_op.add_column(
            sa.Column("specializations", sa.JSON(), server_default=sa.text("'[]'"), nullable=False)
        )
        batch_op.add_column(sa.Column("calendar_color", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("teams") as batch_op:
        batch_op.drop_column("calendar_color")
        batch_op.drop_column("specializations")
        batch_op.drop_column("zones")
        batch_op.drop_column("lead_worker_id")
