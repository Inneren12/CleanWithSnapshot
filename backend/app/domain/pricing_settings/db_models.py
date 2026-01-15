from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.infra.db import Base, UUID_TYPE
from app.settings import settings


class ServiceType(Base):
    __tablename__ = "service_types"
    __table_args__ = (
        Index("ix_service_types_org_id", "org_id"),
        sa.UniqueConstraint("org_id", "name", name="uq_service_types_org_name"),
    )

    service_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    pricing_model: Mapped[str] = mapped_column(String(32), nullable=False, default="flat")
    base_price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hourly_rate_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=lambda: settings.deposit_currency.upper()
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    addons: Mapped[list["ServiceAddon"]] = relationship(
        "ServiceAddon",
        back_populates="service_type",
        cascade="all, delete-orphan",
        order_by="ServiceAddon.addon_id",
    )


class ServiceAddon(Base):
    __tablename__ = "service_addons"
    __table_args__ = (
        Index("ix_service_addons_service_type", "service_type_id"),
        sa.UniqueConstraint("service_type_id", "name", name="uq_service_addons_service_name"),
    )

    addon_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_type_id: Mapped[int] = mapped_column(
        ForeignKey("service_types.service_type_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    service_type: Mapped[ServiceType] = relationship("ServiceType", back_populates="addons")


class PricingSettings(Base):
    __tablename__ = "pricing_settings"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, ForeignKey("organizations.org_id", ondelete="CASCADE"), primary_key=True
    )
    gst_rate: Mapped[float] = mapped_column(sa.Numeric(6, 4), nullable=False, default=0.0)
    discounts: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    surcharges: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    promo_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BookingPolicy(Base):
    __tablename__ = "booking_policies"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, ForeignKey("organizations.org_id", ondelete="CASCADE"), primary_key=True
    )
    deposit_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    cancellation_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reschedule_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    payment_terms: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scheduling: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
