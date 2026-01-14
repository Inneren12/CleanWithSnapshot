"""add worker reviews and notes

Revision ID: 0071_worker_reviews_and_notes
Revises: 0070_add_worker_skills_and_ratings
Create Date: 2025-09-22 00:00:00.000000
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0071_worker_reviews_and_notes"
down_revision = "0070_add_worker_skills_and_ratings"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.create_table(
        "worker_reviews",
        sa.Column("review_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column(
            "booking_id",
            sa.String(length=36),
            sa.ForeignKey("bookings.booking_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.worker_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=2000)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_worker_reviews_org_id", "worker_reviews", ["org_id"])
    op.create_index("ix_worker_reviews_worker_id", "worker_reviews", ["worker_id"])
    op.create_index("ix_worker_reviews_booking_id", "worker_reviews", ["booking_id"])
    op.create_index("ix_worker_reviews_created_at", "worker_reviews", ["created_at"])

    op.create_table(
        "worker_notes",
        sa.Column("note_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.worker_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "booking_id",
            sa.String(length=36),
            sa.ForeignKey("bookings.booking_id", ondelete="CASCADE"),
        ),
        sa.Column("note_type", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20)),
        sa.Column("text", sa.String(length=2000), nullable=False),
        sa.Column("created_by", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_worker_notes_org_id", "worker_notes", ["org_id"])
    op.create_index("ix_worker_notes_worker_id", "worker_notes", ["worker_id"])
    op.create_index("ix_worker_notes_booking_id", "worker_notes", ["booking_id"])
    op.create_index("ix_worker_notes_note_type", "worker_notes", ["note_type"])
    op.create_index("ix_worker_notes_created_at", "worker_notes", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_worker_notes_created_at", table_name="worker_notes")
    op.drop_index("ix_worker_notes_note_type", table_name="worker_notes")
    op.drop_index("ix_worker_notes_booking_id", table_name="worker_notes")
    op.drop_index("ix_worker_notes_worker_id", table_name="worker_notes")
    op.drop_index("ix_worker_notes_org_id", table_name="worker_notes")
    op.drop_table("worker_notes")

    op.drop_index("ix_worker_reviews_created_at", table_name="worker_reviews")
    op.drop_index("ix_worker_reviews_booking_id", table_name="worker_reviews")
    op.drop_index("ix_worker_reviews_worker_id", table_name="worker_reviews")
    op.drop_index("ix_worker_reviews_org_id", table_name="worker_reviews")
    op.drop_table("worker_reviews")
