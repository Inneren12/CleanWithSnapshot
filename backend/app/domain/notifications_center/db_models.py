from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import UUID_TYPE, Base
from app.settings import settings


class NotificationEvent(Base):
    __tablename__ = "notifications_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    action_href: Mapped[str | None] = mapped_column(String(255))
    action_kind: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        Index("ix_notifications_events_org_created", "org_id", "created_at"),
        Index("ix_notifications_events_org_priority", "org_id", "priority"),
    )


class NotificationRead(Base):
    __tablename__ = "notifications_reads"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("notifications_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_notifications_reads_user_event"),
        Index("ix_notifications_reads_org_user", "org_id", "user_id"),
        Index("ix_notifications_reads_event", "event_id"),
    )
