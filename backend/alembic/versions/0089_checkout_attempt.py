"""add checkout_attempts table for pre-write payment state

Revision ID: 0089_checkout_attempt
Revises: 0088_client_users_rls_from_bookings
Create Date: 2026-02-22 00:00:00.000000

Adds a checkout_attempts table to persist a PENDING row before calling Stripe,
reducing the crash window between Stripe session creation and the DB record.

Status lifecycle:
  PENDING  – inserted before the Stripe API call (Phase 0, small commit)
  CREATED  – updated after Stripe responds and booking IDs are attached (Phase 2)
  FAILED   – updated when Stripe or Phase-2 raises (error_type holds exception
             class name; no PII)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0089_checkout_attempt"
down_revision = "0088_client_users_rls_from_bookings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checkout_attempts",
        sa.Column("attempt_id", sa.String(36), primary_key=True),
        sa.Column(
            "booking_id",
            sa.String(36),
            sa.ForeignKey("bookings.booking_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("stripe_session_id", sa.String(255), nullable=True),
        sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_type", sa.String(64), nullable=True),
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
        sa.UniqueConstraint("idempotency_key", name="uq_checkout_attempts_idempotency_key"),
    )
    op.create_index("ix_checkout_attempts_booking_id", "checkout_attempts", ["booking_id"])


def downgrade() -> None:
    op.drop_index("ix_checkout_attempts_booking_id", table_name="checkout_attempts")
    op.drop_table("checkout_attempts")
