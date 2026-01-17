"""add quality issue tags

Revision ID: 9b7c1d2e3f4a
Revises: 6ddda2f1b93a
Create Date: 2026-01-22 09:15:00.000000

"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

revision = "9b7c1d2e3f4a"
down_revision = "6ddda2f1b93a"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.create_table(
        "quality_tag_catalog",
        sa.Column("tag_key", sa.String(length=64), primary_key=True),
        sa.Column("label", sa.String(length=120), nullable=False),
    )
    op.create_table(
        "quality_issue_tags",
        sa.Column(
            "issue_id",
            UUID_TYPE,
            sa.ForeignKey("quality_issues.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_key",
            sa.String(length=64),
            sa.ForeignKey("quality_tag_catalog.tag_key", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("issue_id", "tag_key", name="uq_quality_issue_tags_issue_id_tag_key"),
    )
    op.create_index("ix_quality_issue_tags_org_id", "quality_issue_tags", ["org_id"])
    op.create_index("ix_quality_issue_tags_issue_id", "quality_issue_tags", ["issue_id"])
    op.create_index("ix_quality_issue_tags_tag_key", "quality_issue_tags", ["tag_key"])

    catalog_table = sa.table(
        "quality_tag_catalog",
        sa.column("tag_key", sa.String(length=64)),
        sa.column("label", sa.String(length=120)),
    )
    op.bulk_insert(
        catalog_table,
        [
            {"tag_key": "lateness", "label": "Lateness"},
            {"tag_key": "missed_spots", "label": "Missed spots"},
            {"tag_key": "communication", "label": "Communication"},
            {"tag_key": "supplies", "label": "Supplies"},
            {"tag_key": "time_overrun", "label": "Time overrun"},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_quality_issue_tags_tag_key", table_name="quality_issue_tags")
    op.drop_index("ix_quality_issue_tags_issue_id", table_name="quality_issue_tags")
    op.drop_index("ix_quality_issue_tags_org_id", table_name="quality_issue_tags")
    op.drop_table("quality_issue_tags")
    op.drop_table("quality_tag_catalog")
