"""add training courses and assignments

Revision ID: e22772c768e9
Revises: a9a9247301a9
Create Date: 2026-01-17 10:13:02.698409

"""
from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

revision = "e22772c768e9"
down_revision = "a9a9247301a9"
branch_labels = None
depends_on = None


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


def downgrade() -> None:
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
