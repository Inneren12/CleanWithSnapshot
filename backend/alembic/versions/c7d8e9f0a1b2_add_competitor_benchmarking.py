"""add competitor benchmarking tables

Revision ID: c7d8e9f0a1b2
Revises: b5c6d7e8f9a0
Create Date: 2026-02-10 09:15:00.000000

"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

revision = "c7d8e9f0a1b2"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.create_table(
        "competitors",
        sa.Column("competitor_id", UUID_TYPE, primary_key=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=120)),
        sa.Column("profile_url", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_competitors_org_id", "competitors", ["org_id"])
    op.create_index("ix_competitors_org_name", "competitors", ["org_id", "name"])

    op.create_table(
        "competitor_metrics",
        sa.Column("metric_id", UUID_TYPE, primary_key=True),
        sa.Column(
            "competitor_id",
            UUID_TYPE,
            sa.ForeignKey("competitors.competitor_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("rating", sa.Float()),
        sa.Column("review_count", sa.Integer()),
        sa.Column("avg_response_hours", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_competitor_metrics_competitor_id",
        "competitor_metrics",
        ["competitor_id"],
    )
    op.create_index(
        "ix_competitor_metrics_competitor_date",
        "competitor_metrics",
        ["competitor_id", "as_of_date"],
    )
    op.create_index(
        "ix_competitor_metrics_as_of_date",
        "competitor_metrics",
        ["as_of_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_competitor_metrics_as_of_date", table_name="competitor_metrics")
    op.drop_index("ix_competitor_metrics_competitor_date", table_name="competitor_metrics")
    op.drop_index("ix_competitor_metrics_competitor_id", table_name="competitor_metrics")
    op.drop_table("competitor_metrics")
    op.drop_index("ix_competitors_org_name", table_name="competitors")
    op.drop_index("ix_competitors_org_id", table_name="competitors")
    op.drop_table("competitors")
