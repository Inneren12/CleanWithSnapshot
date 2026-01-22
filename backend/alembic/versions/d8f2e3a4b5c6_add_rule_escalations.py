"""add rule escalation policies and cooldown tracking

Revision ID: d8f2e3a4b5c6
Revises: e3f4a5b6c7d8
Create Date: 2026-02-20 10:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

revision = "d8f2e3a4b5c6"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("ix_rule_escalations_rule_occurred", table_name="rule_escalations")
    op.drop_index("ix_rule_escalations_org_rule_entity", table_name="rule_escalations")
    op.drop_table("rule_escalations")

    op.drop_column("rules", "escalation_cooldown_minutes")
    op.drop_column("rules", "escalation_policy_json")
