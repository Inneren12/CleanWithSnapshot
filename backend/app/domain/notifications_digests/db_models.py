from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
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
