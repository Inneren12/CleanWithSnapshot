from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base, UUID_TYPE
from app.settings import settings


class QualityIssue(Base):
    __tablename__ = "quality_issues"
    __table_args__ = (
        Index("ix_quality_issues_org_id", "org_id"),
        Index("ix_quality_issues_org_status", "org_id", "status"),
        Index("ix_quality_issues_org_severity", "org_id", "severity"),
        Index("ix_quality_issues_org_created", "org_id", "created_at"),
        Index("ix_quality_issues_booking_id", "booking_id"),
        Index("ix_quality_issues_worker_id", "worker_id"),
        Index("ix_quality_issues_client_id", "client_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    booking_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("bookings.booking_id", ondelete="SET NULL"),
        nullable=True,
    )
    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("client_users.client_id", ondelete="SET NULL"),
        nullable=True,
    )
    rating: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[str | None] = mapped_column(Text())
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="open", server_default="open"
    )
    severity: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_type: Mapped[str | None] = mapped_column(String(64))
    resolution_value: Mapped[str | None] = mapped_column(String(255))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    responses: Mapped[list["QualityIssueResponse"]] = relationship(
        "QualityIssueResponse",
        back_populates="issue",
        cascade="all, delete-orphan",
    )
    tags: Mapped[list["QualityIssueTag"]] = relationship(
        "QualityIssueTag",
        back_populates="issue",
        cascade="all, delete-orphan",
    )
    booking = relationship("Booking")
    worker = relationship("Worker")
    client = relationship("ClientUser")
    assignee = relationship("User")


class QualityIssueResponse(Base):
    __tablename__ = "quality_issue_responses"
    __table_args__ = (
        Index("ix_quality_issue_responses_org_id", "org_id"),
        Index("ix_quality_issue_responses_issue_id", "issue_id"),
    )

    response_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    issue_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("quality_issues.id", ondelete="CASCADE"),
        nullable=False,
    )
    response_type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text(), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    issue = relationship("QualityIssue", back_populates="responses")


class QualityReviewReply(Base):
    __tablename__ = "quality_review_replies"
    __table_args__ = (
        Index("ix_quality_review_replies_org_id", "org_id"),
        Index("ix_quality_review_replies_feedback_id", "feedback_id"),
    )

    reply_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    feedback_id: Mapped[int] = mapped_column(
        ForeignKey("client_feedback.feedback_id", ondelete="CASCADE"),
        nullable=False,
    )
    template_key: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text(), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class QualityTagCatalog(Base):
    __tablename__ = "quality_tag_catalog"

    tag_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)


class QualityIssueTag(Base):
    __tablename__ = "quality_issue_tags"
    __table_args__ = (
        UniqueConstraint("issue_id", "tag_key", name="uq_quality_issue_tags_issue_id_tag_key"),
        Index("ix_quality_issue_tags_org_id", "org_id"),
        Index("ix_quality_issue_tags_issue_id", "issue_id"),
        Index("ix_quality_issue_tags_issue_id_position", "issue_id", "position"),
        Index("ix_quality_issue_tags_tag_key", "tag_key"),
    )

    issue_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("quality_issues.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("quality_tag_catalog.tag_key", ondelete="CASCADE"),
        primary_key=True,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    position: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    issue: Mapped["QualityIssue"] = relationship("QualityIssue", back_populates="tags")
