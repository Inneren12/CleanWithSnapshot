"""add finance expenses and budgets

Revision ID: f2a4b7c8d9e0
Revises: c6f2b8d1a4e7
Create Date: 2026-02-18 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

revision = "f2a4b7c8d9e0"
down_revision = "c6f2b8d1a4e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_expense_categories",
        sa.Column("category_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("category_id"),
    )
    op.create_index(
        "ix_finance_expense_categories_org_id",
        "finance_expense_categories",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        "ix_finance_expense_categories_org_sort",
        "finance_expense_categories",
        ["org_id", "sort_order"],
        unique=False,
    )

    op.create_table(
        "finance_expenses",
        sa.Column("expense_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("category_id", UUID_TYPE, nullable=False),
        sa.Column("vendor", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "tax_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("receipt_url", sa.Text(), nullable=True),
        sa.Column("payment_method", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by_user_id", UUID_TYPE, nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["finance_expense_categories.category_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("expense_id"),
    )
    op.create_index(
        "ix_finance_expenses_org_id",
        "finance_expenses",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        "ix_finance_expenses_org_occurred",
        "finance_expenses",
        ["org_id", "occurred_on"],
        unique=False,
    )
    op.create_index(
        "ix_finance_expenses_org_category",
        "finance_expenses",
        ["org_id", "category_id"],
        unique=False,
    )

    op.create_table(
        "finance_budgets",
        sa.Column("budget_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("month_yyyymm", sa.String(length=7), nullable=False),
        sa.Column("category_id", UUID_TYPE, nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["finance_expense_categories.category_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("budget_id"),
        sa.UniqueConstraint(
            "org_id",
            "month_yyyymm",
            "category_id",
            name="uq_finance_budgets_org_month_category",
        ),
    )
    op.create_index(
        "ix_finance_budgets_org_id",
        "finance_budgets",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        "ix_finance_budgets_org_month",
        "finance_budgets",
        ["org_id", "month_yyyymm"],
        unique=False,
    )
    op.create_index(
        "ix_finance_budgets_org_category",
        "finance_budgets",
        ["org_id", "category_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_finance_budgets_org_category", table_name="finance_budgets")
    op.drop_index("ix_finance_budgets_org_month", table_name="finance_budgets")
    op.drop_index("ix_finance_budgets_org_id", table_name="finance_budgets")
    op.drop_table("finance_budgets")

    op.drop_index("ix_finance_expenses_org_category", table_name="finance_expenses")
    op.drop_index("ix_finance_expenses_org_occurred", table_name="finance_expenses")
    op.drop_index("ix_finance_expenses_org_id", table_name="finance_expenses")
    op.drop_table("finance_expenses")

    op.drop_index("ix_finance_expense_categories_org_sort", table_name="finance_expense_categories")
    op.drop_index("ix_finance_expense_categories_org_id", table_name="finance_expense_categories")
    op.drop_table("finance_expense_categories")
