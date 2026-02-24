"""Alter outbox_events.org_id to UUID

Revision ID: 0f9a8b7c6d5e
Revises: ff1a2b3c4d5e
Create Date: 2026-03-20 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0f9a8b7c6d5e"
down_revision = "ff1a2b3c4d5e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "outbox_events",
        "org_id",
        type_=postgresql.UUID(),
        postgresql_using="org_id::uuid",
        existing_type=sa.String(length=36),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "outbox_events",
        "org_id",
        type_=sa.String(length=36),
        postgresql_using="org_id::text",
        existing_type=postgresql.UUID(),
        existing_nullable=False,
    )
