"""add training requirements and records

Revision ID: b7f4d2e9c1a0
Revises: aa12b3cd45ef
Create Date: 2026-02-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "b7f4d2e9c1a0"
down_revision = "aa12b3cd45ef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_requirements",
        sa.Column("requirement_id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("renewal_months", sa.Integer(), nullable=True),
        sa.Column("required_for_role", sa.String(length=80), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "key", name="uq_training_requirements_org_key"),
    )
    op.create_index("ix_training_requirements_org_id", "training_requirements", ["org_id"])
    op.create_index(
        "ix_training_requirements_org_active",
        "training_requirements",
        ["org_id", "active"],
    )
    op.create_index("ix_training_requirements_key", "training_requirements", ["key"])
    op.create_index(
        "ix_training_requirements_required_for_role",
        "training_requirements",
        ["required_for_role"],
    )

    op.create_table(
        "worker_training_records",
        sa.Column("record_id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.worker_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requirement_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("training_requirements.requirement_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_worker_training_records_org_id", "worker_training_records", ["org_id"])
    op.create_index(
        "ix_worker_training_records_worker_id", "worker_training_records", ["worker_id"]
    )
    op.create_index(
        "ix_worker_training_records_requirement_id",
        "worker_training_records",
        ["requirement_id"],
    )
    op.create_index(
        "ix_worker_training_records_expires_at",
        "worker_training_records",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_worker_training_records_expires_at", table_name="worker_training_records")
    op.drop_index("ix_worker_training_records_requirement_id", table_name="worker_training_records")
    op.drop_index("ix_worker_training_records_worker_id", table_name="worker_training_records")
    op.drop_index("ix_worker_training_records_org_id", table_name="worker_training_records")
    op.drop_table("worker_training_records")

    op.drop_index("ix_training_requirements_required_for_role", table_name="training_requirements")
    op.drop_index("ix_training_requirements_key", table_name="training_requirements")
    op.drop_index("ix_training_requirements_org_active", table_name="training_requirements")
    op.drop_index("ix_training_requirements_org_id", table_name="training_requirements")
    op.drop_table("training_requirements")
