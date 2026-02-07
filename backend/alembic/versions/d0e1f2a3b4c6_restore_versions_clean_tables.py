"""restore tables lost when versions_clean was removed

Revision ID: d0e1f2a3b4c6
Revises: 1b9c3d4e5f6a
Create Date: 2026-04-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d0e1f2a3b4c6"
down_revision = "1b9c3d4e5f6a"
branch_labels = None
depends_on = "c1a2b3c4d5e6"

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "training_courses",
        sa.Column("course_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("format", sa.String(length=40), nullable=True),
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
        sa.PrimaryKeyConstraint("course_id"),
    )
    op.create_index("ix_training_courses_org_id", "training_courses", ["org_id"], unique=False)
    op.create_index(
        "ix_training_courses_org_active",
        "training_courses",
        ["org_id", "active"],
        unique=False,
    )
    op.create_index("ix_training_courses_title", "training_courses", ["title"], unique=False)

    op.create_table(
        "training_assignments",
        sa.Column("assignment_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("course_id", UUID_TYPE, nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'assigned'"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("assigned_by_user_id", UUID_TYPE, nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.org_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["training_courses.course_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["workers.worker_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("assignment_id"),
    )
    op.create_index(
        "ix_training_assignments_org_id",
        "training_assignments",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        "ix_training_assignments_course_id",
        "training_assignments",
        ["course_id"],
        unique=False,
    )
    op.create_index(
        "ix_training_assignments_worker_id",
        "training_assignments",
        ["worker_id"],
        unique=False,
    )
    op.create_index(
        "ix_training_assignments_status",
        "training_assignments",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_training_assignments_due_at",
        "training_assignments",
        ["due_at"],
        unique=False,
    )

    op.create_table(
        "training_sessions",
        sa.Column("session_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("instructor_user_id", UUID_TYPE, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.org_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("ix_training_sessions_org_id", "training_sessions", ["org_id"], unique=False)
    op.create_index(
        "ix_training_sessions_window",
        "training_sessions",
        ["starts_at", "ends_at"],
        unique=False,
    )

    op.create_table(
        "training_session_attendees",
        sa.Column("session_id", UUID_TYPE, nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'enrolled'"),
        ),
        sa.Column("block_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["training_sessions.session_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["workers.worker_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["availability_blocks.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("session_id", "worker_id"),
        sa.UniqueConstraint("session_id", "worker_id", name="uq_training_session_attendee"),
    )
    op.create_index(
        "ix_training_session_attendees_worker",
        "training_session_attendees",
        ["worker_id"],
        unique=False,
    )
    op.create_index(
        "ix_training_session_attendees_status",
        "training_session_attendees",
        ["status"],
        unique=False,
    )

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

    op.create_table(
        "integrations_accounting_accounts",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("realm_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "provider"),
    )
    op.create_index(
        "ix_integrations_accounting_accounts_org_id",
        "integrations_accounting_accounts",
        ["org_id"],
        unique=False,
    )

    op.create_table(
        "accounting_sync_state",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "provider"),
    )
    op.create_index(
        "ix_accounting_sync_state_org_id",
        "accounting_sync_state",
        ["org_id"],
        unique=False,
    )

    op.create_table(
        "accounting_invoice_map",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("local_invoice_id", sa.String(length=36), nullable=False),
        sa.Column("remote_invoice_id", sa.Text(), nullable=False),
        sa.Column("last_pushed_hash", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["local_invoice_id"], ["invoices.invoice_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "local_invoice_id"),
        sa.UniqueConstraint(
            "org_id",
            "remote_invoice_id",
            name="uq_accounting_invoice_map_org_remote",
        ),
    )
    op.create_index(
        "ix_accounting_invoice_map_org_id",
        "accounting_invoice_map",
        ["org_id"],
        unique=False,
    )

    op.add_column(
        "rules",
        sa.Column(
            "escalation_policy_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "rules",
        sa.Column(
            "escalation_cooldown_minutes",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
    )

    op.create_table(
        "rule_escalations",
        sa.Column("escalation_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("rule_id", UUID_TYPE, nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column(
            "levels_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.rule_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("escalation_id"),
    )
    op.create_index(
        "ix_rule_escalations_org_rule_entity",
        "rule_escalations",
        ["org_id", "rule_id", "entity_type", "entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_rule_escalations_rule_occurred",
        "rule_escalations",
        ["rule_id", "occurred_at"],
        unique=False,
    )

    op.create_table(
        "booking_photos",
        sa.Column("photo_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("booking_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("consent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("uploaded_by", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.booking_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("photo_id"),
    )
    op.create_index("ix_booking_photos_booking_id", "booking_photos", ["booking_id"], unique=False)
    op.create_index(
        "ix_booking_photos_org_booking",
        "booking_photos",
        ["org_id", "booking_id"],
        unique=False,
    )
    op.create_index(
        "ix_booking_photos_org_created_at",
        "booking_photos",
        ["org_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_booking_photos_org_id", "booking_photos", ["org_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_booking_photos_org_id", table_name="booking_photos")
    op.drop_index("ix_booking_photos_org_created_at", table_name="booking_photos")
    op.drop_index("ix_booking_photos_org_booking", table_name="booking_photos")
    op.drop_index("ix_booking_photos_booking_id", table_name="booking_photos")
    op.drop_table("booking_photos")

    op.drop_index("ix_rule_escalations_rule_occurred", table_name="rule_escalations")
    op.drop_index("ix_rule_escalations_org_rule_entity", table_name="rule_escalations")
    op.drop_table("rule_escalations")

    op.drop_column("rules", "escalation_cooldown_minutes")
    op.drop_column("rules", "escalation_policy_json")

    op.drop_index("ix_accounting_invoice_map_org_id", table_name="accounting_invoice_map")
    op.drop_table("accounting_invoice_map")

    op.drop_index("ix_accounting_sync_state_org_id", table_name="accounting_sync_state")
    op.drop_table("accounting_sync_state")

    op.drop_index(
        "ix_integrations_accounting_accounts_org_id",
        table_name="integrations_accounting_accounts",
    )
    op.drop_table("integrations_accounting_accounts")

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

    op.drop_index(
        "ix_training_session_attendees_status",
        table_name="training_session_attendees",
    )
    op.drop_index(
        "ix_training_session_attendees_worker",
        table_name="training_session_attendees",
    )
    op.drop_table("training_session_attendees")

    op.drop_index("ix_training_sessions_window", table_name="training_sessions")
    op.drop_index("ix_training_sessions_org_id", table_name="training_sessions")
    op.drop_table("training_sessions")

    op.drop_index("ix_training_assignments_due_at", table_name="training_assignments")
    op.drop_index("ix_training_assignments_status", table_name="training_assignments")
    op.drop_index("ix_training_assignments_worker_id", table_name="training_assignments")
    op.drop_index("ix_training_assignments_course_id", table_name="training_assignments")
    op.drop_index("ix_training_assignments_org_id", table_name="training_assignments")
    op.drop_table("training_assignments")

    op.drop_index("ix_training_courses_title", table_name="training_courses")
    op.drop_index("ix_training_courses_org_active", table_name="training_courses")
    op.drop_index("ix_training_courses_org_id", table_name="training_courses")
    op.drop_table("training_courses")
