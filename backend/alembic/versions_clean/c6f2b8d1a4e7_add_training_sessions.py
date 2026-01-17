"""add training sessions

Revision ID: c6f2b8d1a4e7
Revises: e22772c768e9
Create Date: 2026-02-12 10:04:12.000000

"""
from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

revision = "c6f2b8d1a4e7"
down_revision = "e22772c768e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
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
