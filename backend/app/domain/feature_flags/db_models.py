from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base


class FeatureFlagLifecycleState(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRED = "expired"
    RETIRED = "retired"


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class FeatureFlagDefinition(Base):
    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(1024), nullable=False)
    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.text("false"), default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=sa.func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=FeatureFlagLifecycleState.DRAFT.value
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    evaluate_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )
