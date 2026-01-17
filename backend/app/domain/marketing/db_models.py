from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base, UUID_TYPE
from app.settings import settings


class PromoCode(Base):
    __tablename__ = "promo_codes"
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_promo_codes_org_code"),
        Index("ix_promo_codes_org_active", "org_id", "active"),
    )

    promo_code_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text())
    discount_type: Mapped[str] = mapped_column(String(24), nullable=False)
    percent_off: Mapped[int | None] = mapped_column(Integer)
    amount_cents: Mapped[int | None] = mapped_column(Integer)
    free_addon_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_addons.addon_id"), nullable=True
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_time_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.false()
    )
    min_order_cents: Mapped[int | None] = mapped_column(Integer)
    one_per_customer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.false()
    )
    usage_limit: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa.true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    redemptions: Mapped[list["PromoCodeRedemption"]] = relationship(
        "PromoCodeRedemption",
        back_populates="promo_code",
        cascade="all, delete-orphan",
    )


class PromoCodeRedemption(Base):
    __tablename__ = "promo_code_redemptions"
    __table_args__ = (
        Index("ix_promo_code_redemptions_org_code", "org_id", "promo_code_id"),
        Index("ix_promo_code_redemptions_org_client", "org_id", "client_id"),
        Index("ix_promo_code_redemptions_org_booking", "org_id", "booking_id"),
    )

    redemption_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    promo_code_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("promo_codes.promo_code_id", ondelete="CASCADE"),
        nullable=False,
    )
    booking_id: Mapped[str | None] = mapped_column(
        ForeignKey("bookings.booking_id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[str | None] = mapped_column(
        ForeignKey("client_users.client_id", ondelete="SET NULL"), nullable=True
    )
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    promo_code: Mapped[PromoCode] = relationship("PromoCode", back_populates="redemptions")
