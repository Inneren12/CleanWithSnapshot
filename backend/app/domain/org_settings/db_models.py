from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.infra.db import Base, UUID_TYPE


class OrganizationSettings(Base):
    __tablename__ = "organization_settings"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("organizations.org_id", ondelete="CASCADE"), primary_key=True
    )
    timezone: Mapped[str] = mapped_column(sa.String(128), nullable=False, server_default="America/Edmonton")
    currency: Mapped[str] = mapped_column(sa.String(16), nullable=False, server_default="CAD")
    language: Mapped[str] = mapped_column(sa.String(16), nullable=False, server_default="en")
    business_hours: Mapped[dict] = mapped_column(JSON, default=dict, server_default=sa.text("'{}'"))
    holidays: Mapped[list[str]] = mapped_column(JSON, default=list, server_default=sa.text("'[]'"))
    legal_name: Mapped[str | None] = mapped_column(sa.String(255))
    legal_bn: Mapped[str | None] = mapped_column(sa.String(64))
    legal_gst_hst: Mapped[str | None] = mapped_column(sa.String(64))
    legal_address: Mapped[str | None] = mapped_column(sa.Text())
    legal_phone: Mapped[str | None] = mapped_column(sa.String(64))
    legal_email: Mapped[str | None] = mapped_column(sa.String(255))
    legal_website: Mapped[str | None] = mapped_column(sa.String(255))
    branding: Mapped[dict] = mapped_column(JSON, default=dict, server_default=sa.text("'{}'"))
    referral_credit_trigger: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, server_default="booking_confirmed"
    )
    finance_ready: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.text("false")
    )
    max_users: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    max_storage_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    storage_bytes_used: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, default=0, server_default="0"
    )
    data_export_request_rate_limit_per_minute: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    data_export_request_rate_limit_per_hour: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    data_export_download_rate_limit_per_minute: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    data_export_download_failure_limit_per_window: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    data_export_download_lockout_limit_per_window: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    data_export_cooldown_minutes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )
