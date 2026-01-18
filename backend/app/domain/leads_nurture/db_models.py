from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON
import sqlalchemy as sa

from app.domain.leads_nurture.statuses import (
    NurtureChannel,
    NurtureEnrollmentStatus,
    NurtureStepLogStatus,
)
from app.infra.db import Base, UUID_TYPE
from app.settings import settings


class NurtureCampaign(Base):
    __tablename__ = "nurture_campaigns"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    steps: Mapped[list["NurtureStep"]] = relationship(
        "NurtureStep",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    enrollments: Mapped[list["NurtureEnrollment"]] = relationship(
        "NurtureEnrollment",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        sa.UniqueConstraint("org_id", "key", name="uq_nurture_campaigns_org_key"),
        Index("ix_nurture_campaigns_org_id", "org_id"),
    )


class NurtureStep(Base):
    __tablename__ = "nurture_steps"

    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("nurture_campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    delay_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[NurtureChannel] = mapped_column(
        sa.Enum(NurtureChannel, name="nurture_channel"),
        nullable=False,
    )
    template_key: Mapped[str | None] = mapped_column(String(255))
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    campaign: Mapped[NurtureCampaign] = relationship("NurtureCampaign", back_populates="steps")

    __table_args__ = (
        sa.UniqueConstraint(
            "org_id",
            "campaign_id",
            "step_index",
            name="uq_nurture_steps_org_campaign_index",
        ),
        Index("ix_nurture_steps_org_campaign", "org_id", "campaign_id"),
    )


class NurtureEnrollment(Base):
    __tablename__ = "nurture_enrollments"

    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    lead_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("leads.lead_id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("nurture_campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    status: Mapped[NurtureEnrollmentStatus] = mapped_column(
        sa.Enum(NurtureEnrollmentStatus, name="nurture_enrollment_status"),
        nullable=False,
        default=NurtureEnrollmentStatus.active,
        server_default="active",
    )

    campaign: Mapped[NurtureCampaign] = relationship("NurtureCampaign", back_populates="enrollments")
    logs: Mapped[list["NurtureStepLog"]] = relationship(
        "NurtureStepLog",
        back_populates="enrollment",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_nurture_enrollments_org_lead", "org_id", "lead_id"),
        Index("ix_nurture_enrollments_org_campaign", "org_id", "campaign_id"),
    )


class NurtureStepLog(Base):
    __tablename__ = "nurture_step_log"

    log_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("nurture_enrollments.enrollment_id", ondelete="CASCADE"),
        nullable=False,
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[NurtureStepLogStatus] = mapped_column(
        sa.Enum(NurtureStepLogStatus, name="nurture_step_log_status"),
        nullable=False,
        default=NurtureStepLogStatus.planned,
        server_default="planned",
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    enrollment: Mapped[NurtureEnrollment] = relationship("NurtureEnrollment", back_populates="logs")

    __table_args__ = (
        sa.UniqueConstraint("org_id", "idempotency_key", name="uq_nurture_step_log_org_idempotency"),
        Index("ix_nurture_step_log_org_enrollment", "org_id", "enrollment_id"),
    )
