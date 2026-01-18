"""add rules and rule runs

Revision ID: c1a2b3c4d5e6
Revises: f9c1d2e3a4b5
Create Date: 2026-02-25 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c1a2b3c4d5e6"
down_revision = "f9c1d2e3a4b5"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "rules",
        sa.Column("rule_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("conditions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("actions_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rule_id"),
    )
    op.create_index("ix_rules_org_created", "rules", ["org_id", "created_at"])
    op.create_index("ix_rules_org_id", "rules", ["org_id"])

    op.create_table(
        "rule_runs",
        sa.Column("run_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("rule_id", UUID_TYPE, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("matched", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("actions_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.rule_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_rule_runs_org_occurred", "rule_runs", ["org_id", "occurred_at"])
    op.create_index("ix_rule_runs_org_rule", "rule_runs", ["org_id", "rule_id"])
    op.create_index("ix_rule_runs_rule", "rule_runs", ["rule_id"])


def downgrade() -> None:
    op.drop_index("ix_rule_runs_rule", table_name="rule_runs")
    op.drop_index("ix_rule_runs_org_rule", table_name="rule_runs")
    op.drop_index("ix_rule_runs_org_occurred", table_name="rule_runs")
    op.drop_table("rule_runs")
    op.drop_index("ix_rules_org_id", table_name="rules")
    op.drop_index("ix_rules_org_created", table_name="rules")
    op.drop_table("rules")
