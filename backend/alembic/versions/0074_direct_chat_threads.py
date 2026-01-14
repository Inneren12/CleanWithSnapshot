"""direct admin worker chat tables

Revision ID: 0074_direct_chat_threads
Revises: 0073_client_notes_tags_blocked
Create Date: 2025-10-06 00:00:00.000000
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0074_direct_chat_threads"
down_revision = "0073_client_notes_tags_blocked"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.create_table(
        "chat_threads",
        sa.Column("thread_id", UUID_TYPE, primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column("thread_type", sa.String(length=32), nullable=False, server_default="direct"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_threads_org_id", "chat_threads", ["org_id"])
    op.create_index("ix_chat_threads_updated_at", "chat_threads", ["updated_at"])

    op.create_table(
        "chat_participants",
        sa.Column("participant_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column(
            "thread_id",
            UUID_TYPE,
            sa.ForeignKey("chat_threads.thread_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("participant_type", sa.String(length=20), nullable=False),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.worker_id", ondelete="CASCADE"),
        ),
        sa.Column(
            "admin_membership_id",
            sa.Integer(),
            sa.ForeignKey("memberships.membership_id", ondelete="CASCADE"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "thread_id",
            "participant_type",
            "worker_id",
            "admin_membership_id",
            name="uq_chat_participants_thread_participant",
        ),
    )
    op.create_index("ix_chat_participants_org_id", "chat_participants", ["org_id"])
    op.create_index("ix_chat_participants_thread_id", "chat_participants", ["thread_id"])
    op.create_index("ix_chat_participants_worker_id", "chat_participants", ["worker_id"])
    op.create_index("ix_chat_participants_admin_membership_id", "chat_participants", ["admin_membership_id"])

    op.create_table(
        "chat_messages",
        sa.Column("message_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column(
            "thread_id",
            UUID_TYPE,
            sa.ForeignKey("chat_threads.thread_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender_type", sa.String(length=20), nullable=False),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.worker_id", ondelete="SET NULL"),
        ),
        sa.Column(
            "admin_membership_id",
            sa.Integer(),
            sa.ForeignKey("memberships.membership_id", ondelete="SET NULL"),
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_messages_org_id", "chat_messages", ["org_id"])
    op.create_index("ix_chat_messages_thread_id", "chat_messages", ["thread_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])

    op.create_table(
        "chat_thread_reads",
        sa.Column("read_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column(
            "thread_id",
            UUID_TYPE,
            sa.ForeignKey("chat_threads.thread_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("participant_type", sa.String(length=20), nullable=False),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.worker_id", ondelete="CASCADE"),
        ),
        sa.Column(
            "admin_membership_id",
            sa.Integer(),
            sa.ForeignKey("memberships.membership_id", ondelete="CASCADE"),
        ),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "thread_id",
            "participant_type",
            "worker_id",
            "admin_membership_id",
            name="uq_chat_thread_reads_participant",
        ),
    )
    op.create_index("ix_chat_thread_reads_org_id", "chat_thread_reads", ["org_id"])
    op.create_index("ix_chat_thread_reads_thread_id", "chat_thread_reads", ["thread_id"])
    op.create_index("ix_chat_thread_reads_worker_id", "chat_thread_reads", ["worker_id"])
    op.create_index(
        "ix_chat_thread_reads_admin_membership_id",
        "chat_thread_reads",
        ["admin_membership_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_thread_reads_admin_membership_id", table_name="chat_thread_reads")
    op.drop_index("ix_chat_thread_reads_worker_id", table_name="chat_thread_reads")
    op.drop_index("ix_chat_thread_reads_thread_id", table_name="chat_thread_reads")
    op.drop_index("ix_chat_thread_reads_org_id", table_name="chat_thread_reads")
    op.drop_table("chat_thread_reads")

    op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_thread_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_org_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_participants_admin_membership_id", table_name="chat_participants")
    op.drop_index("ix_chat_participants_worker_id", table_name="chat_participants")
    op.drop_index("ix_chat_participants_thread_id", table_name="chat_participants")
    op.drop_index("ix_chat_participants_org_id", table_name="chat_participants")
    op.drop_table("chat_participants")

    op.drop_index("ix_chat_threads_updated_at", table_name="chat_threads")
    op.drop_index("ix_chat_threads_org_id", table_name="chat_threads")
    op.drop_table("chat_threads")

