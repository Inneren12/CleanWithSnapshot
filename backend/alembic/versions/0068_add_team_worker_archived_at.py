"""add archived_at to teams and workers

Revision ID: 0068_add_team_worker_archived_at
Revises: 4a939bab6876
Create Date: 2026-02-15 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0068_add_team_worker_archived_at"
down_revision = "4a939bab6876"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workers", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_teams_archived_at", "teams", ["archived_at"])
    op.create_index("ix_workers_archived_at", "workers", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_workers_archived_at", table_name="workers")
    op.drop_index("ix_teams_archived_at", table_name="teams")
    op.drop_column("workers", "archived_at")
    op.drop_column("teams", "archived_at")
