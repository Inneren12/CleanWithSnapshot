"""add client note types

Revision ID: 0076_client_note_type
Revises: 0075_message_templates
Create Date: 2025-10-06 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0076_client_note_type"
down_revision = "0075_message_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("client_notes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "note_type",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'NOTE'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("client_notes") as batch_op:
        batch_op.drop_column("note_type")
