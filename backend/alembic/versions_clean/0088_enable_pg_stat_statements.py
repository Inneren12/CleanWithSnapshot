"""enable pg_stat_statements extension

Revision ID: 0088_enable_pg_stat_statements
Revises: 0087_client_users_rls_enforce
Create Date: 2026-03-10 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
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

    try:
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "pg_stat_statements extension could not be created. Ensure the database user has "
            "CREATE EXTENSION privileges and Postgres is configured with "
            "shared_preload_libraries=pg_stat_statements (restart required). "
            "Managed services may require enabling the extension via provider settings."
        ) from exc


def downgrade() -> None:
    return
