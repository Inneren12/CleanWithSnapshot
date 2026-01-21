"""add client notes, tags, and blocked status

Revision ID: 0073_client_notes_tags_blocked
Revises: 0072_worker_onboarding_and_certificates
Create Date: 2025-10-05 00:00:00.000000
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0073_client_notes_tags_blocked"
down_revision = "0072_worker_onboarding_and_certificates"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    with op.batch_alter_table("client_users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_blocked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch_op.add_column(sa.Column("tags_json", sa.Text(), nullable=True))

    op.create_table(
        "client_notes",
        sa.Column("note_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column(
            "client_id",
            sa.String(length=36),
            sa.ForeignKey("client_users.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(length=255)),
    )
    op.create_index("ix_client_notes_org_id", "client_notes", ["org_id"])
    op.create_index("ix_client_notes_client_id", "client_notes", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_client_notes_client_id", table_name="client_notes")
    op.drop_index("ix_client_notes_org_id", table_name="client_notes")
    op.drop_table("client_notes")

    with op.batch_alter_table("client_users") as batch_op:
        batch_op.drop_column("tags_json")
        batch_op.drop_column("is_blocked")
