"""add booking photo evidence metadata

Revision ID: b5c6d7e8f9a0
Revises: d8f2e3a4b5c6
Create Date: 2026-02-20 11:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

revision = "b5c6d7e8f9a0"
down_revision = "d8f2e3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "booking_photos",
        sa.Column("photo_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("booking_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("consent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("uploaded_by", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.booking_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("photo_id"),
    )
    op.create_index("ix_booking_photos_booking_id", "booking_photos", ["booking_id"], unique=False)
    op.create_index("ix_booking_photos_org_booking", "booking_photos", ["org_id", "booking_id"], unique=False)
    op.create_index("ix_booking_photos_org_created_at", "booking_photos", ["org_id", "created_at"], unique=False)
    op.create_index("ix_booking_photos_org_id", "booking_photos", ["org_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_booking_photos_org_id", table_name="booking_photos")
    op.drop_index("ix_booking_photos_org_created_at", table_name="booking_photos")
    op.drop_index("ix_booking_photos_org_booking", table_name="booking_photos")
    op.drop_index("ix_booking_photos_booking_id", table_name="booking_photos")
    op.drop_table("booking_photos")
