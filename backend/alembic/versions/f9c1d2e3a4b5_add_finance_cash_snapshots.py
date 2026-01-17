"""add finance cash snapshots

Revision ID: f9c1d2e3a4b5
Revises: f1e2d3c4b5a6
Create Date: 2026-02-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f9c1d2e3a4b5"
down_revision = "f1e2d3c4b5a6"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "finance_cash_snapshots",
        sa.Column("snapshot_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("cash_cents", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.org_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint("org_id", "as_of_date", name="uq_finance_cash_snapshots_org_date"),
    )
    op.create_index(
        "ix_finance_cash_snapshots_org_date",
        "finance_cash_snapshots",
        ["org_id", "as_of_date"],
    )
    op.create_index(
        "ix_finance_cash_snapshots_org_id",
        "finance_cash_snapshots",
        ["org_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_finance_cash_snapshots_org_id", table_name="finance_cash_snapshots")
    op.drop_index("ix_finance_cash_snapshots_org_date", table_name="finance_cash_snapshots")
    op.drop_table("finance_cash_snapshots")
