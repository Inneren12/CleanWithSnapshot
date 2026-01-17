"""add lead quotes and loss reason

Revision ID: d3b7c1a4f8e2
Revises: c2f4b8a1d9e0
Create Date: 2026-02-10 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

revision = "d3b7c1a4f8e2"
down_revision = "c2f4b8a1d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("leads") as batch_op:
        batch_op.add_column(sa.Column("loss_reason", sa.String(length=255), nullable=True))

    op.create_table(
        "lead_quotes",
        sa.Column("quote_id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("service_type", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("quote_id"),
    )
    op.create_index("ix_lead_quotes_org_id", "lead_quotes", ["org_id"])
    op.create_index("ix_lead_quotes_lead_id", "lead_quotes", ["lead_id"])

    op.create_table(
        "lead_quote_followups",
        sa.Column("followup_id", sa.String(length=36), nullable=False),
        sa.Column("quote_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["quote_id"], ["lead_quotes.quote_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("followup_id"),
    )
    op.create_index("ix_lead_quote_followups_org_id", "lead_quote_followups", ["org_id"])
    op.create_index("ix_lead_quote_followups_quote_id", "lead_quote_followups", ["quote_id"])


def downgrade() -> None:
    op.drop_index("ix_lead_quote_followups_quote_id", table_name="lead_quote_followups")
    op.drop_index("ix_lead_quote_followups_org_id", table_name="lead_quote_followups")
    op.drop_table("lead_quote_followups")
    op.drop_index("ix_lead_quotes_lead_id", table_name="lead_quotes")
    op.drop_index("ix_lead_quotes_org_id", table_name="lead_quotes")
    op.drop_table("lead_quotes")

    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_column("loss_reason")
