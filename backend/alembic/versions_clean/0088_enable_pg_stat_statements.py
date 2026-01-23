"""enable pg_stat_statements extension

Revision ID: 0088_enable_pg_stat_statements
Revises: 0087_client_users_rls_enforce
Create Date: 2026-03-10 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0088_enable_pg_stat_statements"
down_revision = "0087_client_users_rls_enforce"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))


def downgrade() -> None:
    if not _is_postgres():
        return

    op.execute(sa.text("DROP EXTENSION IF EXISTS pg_stat_statements"))
