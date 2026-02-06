"""chat participant keys and org defaults

Revision ID: 0079_chat_participant_keys_org_defaults
Revises: 0078_client_feedback
Create Date: 2025-10-06 00:00:00.000000
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0079_chat_participant_keys_org_defaults"
down_revision = "0078_client_feedback"
branch_labels = None
depends_on = None

DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    with op.batch_alter_table("client_users") as batch_op:
        batch_op.alter_column("is_blocked", server_default=sa.false())

    with op.batch_alter_table("chat_threads") as batch_op:
        batch_op.alter_column("org_id", server_default=None)

    with op.batch_alter_table("chat_participants") as batch_op:
        batch_op.add_column(sa.Column("participant_key", sa.Text(), nullable=True))

    op.execute(
        sa.text(
            "UPDATE chat_participants "
            "SET participant_key = participant_type || ':' || "
            "COALESCE(CAST(worker_id AS TEXT), CAST(admin_membership_id AS TEXT))"
        )
    )

    with op.batch_alter_table("chat_participants") as batch_op:
        batch_op.alter_column("participant_key", nullable=False)
        batch_op.drop_constraint("uq_chat_participants_thread_participant", type_="unique")
        batch_op.create_unique_constraint(
            "uq_chat_participants_thread_key",
            ["org_id", "thread_id", "participant_key"],
        )
        batch_op.alter_column("org_id", server_default=None)

    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.alter_column("org_id", server_default=None)

    with op.batch_alter_table("chat_thread_reads") as batch_op:
        batch_op.add_column(sa.Column("participant_key", sa.Text(), nullable=True))

    op.execute(
        sa.text(
            "UPDATE chat_thread_reads "
            "SET participant_key = participant_type || ':' || "
            "COALESCE(CAST(worker_id AS TEXT), CAST(admin_membership_id AS TEXT))"
        )
    )

    with op.batch_alter_table("chat_thread_reads") as batch_op:
        batch_op.alter_column("participant_key", nullable=False)
        batch_op.drop_constraint("uq_chat_thread_reads_participant", type_="unique")
        batch_op.create_unique_constraint(
            "uq_chat_thread_reads_thread_key",
            ["org_id", "thread_id", "participant_key"],
        )
        batch_op.alter_column("org_id", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("chat_thread_reads") as batch_op:
        batch_op.drop_constraint("uq_chat_thread_reads_thread_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_chat_thread_reads_participant",
            ["thread_id", "participant_type", "worker_id", "admin_membership_id"],
        )
        batch_op.drop_column("participant_key")
        batch_op.alter_column("org_id", server_default=sa.text(f"'{DEFAULT_ORG_ID}'"))

    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.alter_column("org_id", server_default=sa.text(f"'{DEFAULT_ORG_ID}'"))

    with op.batch_alter_table("chat_participants") as batch_op:
        batch_op.drop_constraint("uq_chat_participants_thread_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_chat_participants_thread_participant",
            ["thread_id", "participant_type", "worker_id", "admin_membership_id"],
        )
        batch_op.drop_column("participant_key")
        batch_op.alter_column("org_id", server_default=sa.text(f"'{DEFAULT_ORG_ID}'"))

    with op.batch_alter_table("chat_threads") as batch_op:
        batch_op.alter_column("org_id", server_default=sa.text(f"'{DEFAULT_ORG_ID}'"))

    with op.batch_alter_table("client_users") as batch_op:
        batch_op.alter_column("is_blocked", server_default=sa.text("false"))
