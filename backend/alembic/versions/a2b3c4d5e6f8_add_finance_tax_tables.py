"""add finance tax tables

Revision ID: a2b3c4d5e6f8
Revises: f9c1d2e3a4b5
Create Date: 2026-02-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a2b3c4d5e6f8"
down_revision = "f9c1d2e3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_tax_instalments",
        sa.Column("instalment_id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tax_type", sa.String(length=50), nullable=False, server_default="GST"),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_finance_tax_instalments_org_id",
        "finance_tax_instalments",
        ["org_id"],
    )
    op.create_index(
        "ix_finance_tax_instalments_org_due",
        "finance_tax_instalments",
        ["org_id", "due_on"],
    )

    op.create_table(
        "finance_tax_exports",
        sa.Column("export_id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_finance_tax_exports_org_id",
        "finance_tax_exports",
        ["org_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_finance_tax_exports_org_id", table_name="finance_tax_exports")
    op.drop_table("finance_tax_exports")
    op.drop_index("ix_finance_tax_instalments_org_due", table_name="finance_tax_instalments")
    op.drop_index("ix_finance_tax_instalments_org_id", table_name="finance_tax_instalments")
    op.drop_table("finance_tax_instalments")
