"""Add IAM roles and custom role assignments.

Revision ID: 0085_iam_roles_permissions
Revises: 0084_feature_modules_visibility
Create Date: 2026-01-16 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0085_iam_roles_permissions"
down_revision = "0084_feature_modules_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "iam_roles",
        sa.Column("role_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("permissions", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id"),
        sa.UniqueConstraint("org_id", "role_key", name="uq_iam_roles_org_key"),
    )

    with op.batch_alter_table("memberships") as batch_op:
        batch_op.add_column(sa.Column("custom_role_id", sa.Uuid(as_uuid=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_memberships_custom_role",
            "iam_roles",
            ["custom_role_id"],
            ["role_id"],
            ondelete="SET NULL",
        )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE membershiprole ADD VALUE IF NOT EXISTS 'accountant'")


def downgrade() -> None:
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.drop_constraint("fk_memberships_custom_role", type_="foreignkey")
        batch_op.drop_column("custom_role_id")
    op.drop_table("iam_roles")
