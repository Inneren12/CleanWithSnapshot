from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base, UUID_TYPE
from app.settings import settings


class NotificationDigestSetting(Base):
    __tablename__ = "notifications_digest_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    digest_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    schedule: Mapped[str] = mapped_column(String(16), nullable=False)
    recipients: Mapped[list[str]] = mapped_column(
        sa.JSON(), nullable=False, default=list, server_default=sa.text("'[]'")
    )

    __table_args__ = (
        UniqueConstraint("org_id", "digest_key", name="uq_notifications_digest_settings_org_key"),
        Index("ix_notifications_digest_settings_org_id", "org_id"),
    )


class NotificationDigestState(Base):
    __tablename__ = "notifications_digest_state"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        primary_key=True,
        default=lambda: settings.default_org_id,
    )
    digest_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sent_period_key: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (Index("ix_notifications_digest_state_org_id", "org_id"),)
