"""add quality issue responses

Revision ID: 6ddda2f1b93a
Revises: f4bb602b1d9b
Create Date: 2026-01-20 10:12:00.000000

"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

revision = "6ddda2f1b93a"
down_revision = "f4bb602b1d9b"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.create_table(
        "quality_issue_responses",
        sa.Column("response_id", UUID_TYPE, primary_key=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column(
            "issue_id",
            UUID_TYPE,
            sa.ForeignKey("quality_issues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("response_type", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_quality_issue_responses_org_id", "quality_issue_responses", ["org_id"])
    op.create_index("ix_quality_issue_responses_issue_id", "quality_issue_responses", ["issue_id"])


def downgrade() -> None:
    op.drop_index("ix_quality_issue_responses_issue_id", table_name="quality_issue_responses")
    op.drop_index("ix_quality_issue_responses_org_id", table_name="quality_issue_responses")
    op.drop_table("quality_issue_responses")
