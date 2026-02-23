"""add data export ordering index

Revision ID: 2b4c6d8e0f1a
Revises: 53b6a386be3c
Create Date: 2026-03-02 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "2b4c6d8e0f1a"
down_revision = "53b6a386be3c"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_data_export_requests_org_created_export"
TABLE_NAME = "data_export_requests"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE_NAME)}
    if INDEX_NAME not in existing_indexes:
        op.create_index(
            INDEX_NAME,
            TABLE_NAME,
            ["org_id", "created_at", "export_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE_NAME)}
    if INDEX_NAME in existing_indexes:
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
