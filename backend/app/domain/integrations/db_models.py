from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.infra.db import Base, UUID_TYPE
from app.settings import settings


class GcalSyncMode(str, Enum):
    EXPORT = "export"
    IMPORT = "import"
    TWO_WAY = "two_way"


class IntegrationsGoogleAccount(Base):
    __tablename__ = "integrations_google_accounts"

    account_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="google",
        server_default="google",
    )
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_scopes: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        server_default="[]",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_integrations_google_accounts_org_id", "org_id"),)


class IntegrationsGcalCalendar(Base):
    __tablename__ = "integrations_gcal_calendars"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        primary_key=True,
        default=lambda: settings.default_org_id,
    )
    calendar_id: Mapped[str] = mapped_column(Text, primary_key=True)
    mode: Mapped[GcalSyncMode] = mapped_column(
        sa.Enum(GcalSyncMode, name="gcal_sync_mode"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_integrations_gcal_calendars_org_id", "org_id"),)


class IntegrationsGcalSyncState(Base):
    __tablename__ = "integrations_gcal_sync_state"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        primary_key=True,
        default=lambda: settings.default_org_id,
    )
    calendar_id: Mapped[str] = mapped_column(Text, primary_key=True)
    sync_cursor: Mapped[str | None] = mapped_column(Text)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_integrations_gcal_sync_state_org_id", "org_id"),)


class ScheduleExternalBlock(Base):
    __tablename__ = "schedule_external_blocks"

    block_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="gcal",
        server_default="gcal",
    )
    external_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_schedule_external_blocks_org_id", "org_id"),
        sa.UniqueConstraint(
            "org_id",
            "external_event_id",
            name="uq_schedule_external_blocks_org_event",
        ),
    )


class IntegrationsGcalEventMap(Base):
    __tablename__ = "integrations_gcal_event_map"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        primary_key=True,
        default=lambda: settings.default_org_id,
    )
    booking_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    calendar_id: Mapped[str] = mapped_column(Text, primary_key=True)
    external_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    last_pushed_hash: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_integrations_gcal_event_map_org_id", "org_id"),)


class IntegrationsAccountingAccount(Base):
    __tablename__ = "integrations_accounting_accounts"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        primary_key=True,
        default=lambda: settings.default_org_id,
    )
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    realm_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_integrations_accounting_accounts_org_id", "org_id"),)


class AccountingSyncState(Base):
    __tablename__ = "accounting_sync_state"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        primary_key=True,
        default=lambda: settings.default_org_id,
    )
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(Text)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_accounting_sync_state_org_id", "org_id"),)


class AccountingInvoiceMap(Base):
    __tablename__ = "accounting_invoice_map"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        primary_key=True,
        default=lambda: settings.default_org_id,
    )
    local_invoice_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("invoices.invoice_id", ondelete="CASCADE"),
        primary_key=True,
    )
    remote_invoice_id: Mapped[str] = mapped_column(Text, nullable=False)
    last_pushed_hash: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_accounting_invoice_map_org_id", "org_id"),
        sa.UniqueConstraint(
            "org_id",
            "remote_invoice_id",
            name="uq_accounting_invoice_map_org_remote",
        ),
    )


class MapsUsage(Base):
    __tablename__ = "maps_usage"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        primary_key=True,
        default=lambda: settings.default_org_id,
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (Index("ix_maps_usage_org_id", "org_id"),)
