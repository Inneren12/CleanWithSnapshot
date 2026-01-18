from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import UUID_TYPE, Base
from app.settings import settings


class Rule(Base):
    __tablename__ = "rules"

    rule_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False)
    conditions_json: Mapped[dict[str, Any]] = mapped_column(
        sa.JSON(),
        nullable=False,
        default=dict,
        server_default=sa.text("'{}'"),
    )
    actions_json: Mapped[list[Any]] = mapped_column(
        sa.JSON(),
        nullable=False,
        default=list,
        server_default=sa.text("'[]'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_rules_org_id", "org_id"),
        Index("ix_rules_org_created", "org_id", "created_at"),
    )


class RuleRun(Base):
    __tablename__ = "rule_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("rules.rule_id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    actions_json: Mapped[list[Any]] = mapped_column(
        sa.JSON(),
        nullable=False,
        default=list,
        server_default=sa.text("'[]'"),
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_rule_runs_org_rule", "org_id", "rule_id"),
        Index("ix_rule_runs_org_occurred", "org_id", "occurred_at"),
        Index("ix_rule_runs_rule", "rule_id"),
    )
