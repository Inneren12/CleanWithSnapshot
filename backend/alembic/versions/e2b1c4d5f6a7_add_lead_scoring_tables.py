"""add lead scoring tables

Revision ID: e2b1c4d5f6a7
Revises: d8f2e3a4b5c6
Create Date: 2026-02-20 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

revision = "e2b1c4d5f6a7"
down_revision = "d8f2e3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_scoring_rules",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("rules_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "version"),
    )
    op.create_index("ix_lead_scoring_rules_org_id", "lead_scoring_rules", ["org_id"])

    op.create_table(
        "lead_scores_snapshot",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("reasons_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("rules_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "lead_id"),
    )
    op.create_index("ix_lead_scores_snapshot_org_id", "lead_scores_snapshot", ["org_id"])
    op.create_index("ix_lead_scores_snapshot_lead_id", "lead_scores_snapshot", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_lead_scores_snapshot_lead_id", table_name="lead_scores_snapshot")
    op.drop_index("ix_lead_scores_snapshot_org_id", table_name="lead_scores_snapshot")
    op.drop_table("lead_scores_snapshot")

    op.drop_index("ix_lead_scoring_rules_org_id", table_name="lead_scoring_rules")
    op.drop_table("lead_scoring_rules")
