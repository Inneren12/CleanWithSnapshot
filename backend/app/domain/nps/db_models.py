import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base, UUID_TYPE
from app.settings import settings


class NpsToken(Base):
    __tablename__ = "nps_tokens"

    token: Mapped[str] = mapped_column(String(255), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    client_id: Mapped[str | None] = mapped_column(
        ForeignKey("client_users.client_id"), nullable=True
    )
    booking_id: Mapped[str] = mapped_column(
        ForeignKey("bookings.booking_id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    booking = relationship("Booking")
    client = relationship("ClientUser")

    __table_args__ = (
        Index("ix_nps_tokens_org_id", "org_id"),
        Index("ix_nps_tokens_booking_id", "booking_id"),
        Index("ix_nps_tokens_expires_at", "expires_at"),
    )


class NpsResponse(Base):
    __tablename__ = "nps_responses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    token: Mapped[str] = mapped_column(
        ForeignKey("nps_tokens.token", ondelete="CASCADE"),
        nullable=False,
    )
    order_id: Mapped[str] = mapped_column(
        ForeignKey("bookings.booking_id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[str | None] = mapped_column(
        ForeignKey("client_users.client_id"), nullable=True
    )
    score: Mapped[int] = mapped_column(nullable=False)
    comment: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order = relationship("Booking")
    client = relationship("ClientUser")
    nps_token = relationship("NpsToken")

    __table_args__ = (UniqueConstraint("token", name="uq_nps_responses_token"),)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    order_id: Mapped[str] = mapped_column(
        ForeignKey("bookings.booking_id", ondelete="CASCADE"), nullable=False, unique=True
    )
    client_id: Mapped[str | None] = mapped_column(
        ForeignKey("client_users.client_id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String(4000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    order = relationship("Booking")
    client = relationship("ClientUser")

    __table_args__ = (UniqueConstraint("order_id", name="uq_support_tickets_order"),)
