from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.infra.db import Base, UUID_TYPE
from app.settings import settings


class LeadScoringRule(Base):
    __tablename__ = "lead_scoring_rules"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        primary_key=True,
        default=lambda: settings.default_org_id,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    rules_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_lead_scoring_rules_org_id", "org_id"),)


class LeadScoreSnapshot(Base):
    __tablename__ = "lead_scores_snapshot"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        primary_key=True,
        default=lambda: settings.default_org_id,
    )
    lead_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("leads.lead_id", ondelete="CASCADE"),
        primary_key=True,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    reasons_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    rules_version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_lead_scores_snapshot_org_id", "org_id"),
        Index("ix_lead_scores_snapshot_lead_id", "lead_id"),
    )
