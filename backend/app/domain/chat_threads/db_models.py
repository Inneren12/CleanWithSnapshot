from __future__ import annotations

from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base, UUID_TYPE


class ChatThread(Base):
    __tablename__ = "chat_threads"

    thread_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False
    )
    thread_type: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="direct")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    participants: Mapped[list["ChatParticipant"]] = relationship(
        "ChatParticipant", back_populates="thread", cascade="all, delete-orphan"
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="thread", cascade="all, delete-orphan"
    )
    reads: Mapped[list["ChatThreadRead"]] = relationship(
        "ChatThreadRead", back_populates="thread", cascade="all, delete-orphan"
    )

    __table_args__ = (
        sa.Index("ix_chat_threads_org_id", "org_id"),
        sa.Index("ix_chat_threads_updated_at", "updated_at"),
    )


class ChatParticipant(Base):
    __tablename__ = "chat_participants"

    participant_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("chat_threads.thread_id", ondelete="CASCADE"), nullable=False
    )
    participant_type: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    worker_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("workers.worker_id", ondelete="CASCADE")
    )
    admin_membership_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("memberships.membership_id", ondelete="CASCADE")
    )
    participant_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    thread: Mapped["ChatThread"] = relationship("ChatThread", back_populates="participants")

    __table_args__ = (
        sa.Index("ix_chat_participants_org_id", "org_id"),
        sa.Index("ix_chat_participants_thread_id", "thread_id"),
        sa.Index("ix_chat_participants_worker_id", "worker_id"),
        sa.Index("ix_chat_participants_admin_membership_id", "admin_membership_id"),
        sa.UniqueConstraint(
            "org_id",
            "thread_id",
            "participant_key",
            name="uq_chat_participants_thread_key",
        ),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    message_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("chat_threads.thread_id", ondelete="CASCADE"), nullable=False
    )
    sender_type: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    worker_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("workers.worker_id", ondelete="SET NULL")
    )
    admin_membership_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("memberships.membership_id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    thread: Mapped["ChatThread"] = relationship("ChatThread", back_populates="messages")

    __table_args__ = (
        sa.Index("ix_chat_messages_org_id", "org_id"),
        sa.Index("ix_chat_messages_thread_id", "thread_id"),
        sa.Index("ix_chat_messages_created_at", "created_at"),
    )


class ChatThreadRead(Base):
    __tablename__ = "chat_thread_reads"

    read_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("chat_threads.thread_id", ondelete="CASCADE"), nullable=False
    )
    participant_type: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    worker_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("workers.worker_id", ondelete="CASCADE")
    )
    admin_membership_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("memberships.membership_id", ondelete="CASCADE")
    )
    participant_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    last_read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    thread: Mapped["ChatThread"] = relationship("ChatThread", back_populates="reads")

    __table_args__ = (
        sa.Index("ix_chat_thread_reads_org_id", "org_id"),
        sa.Index("ix_chat_thread_reads_thread_id", "thread_id"),
        sa.Index("ix_chat_thread_reads_worker_id", "worker_id"),
        sa.Index("ix_chat_thread_reads_admin_membership_id", "admin_membership_id"),
        sa.UniqueConstraint(
            "org_id",
            "thread_id",
            "participant_key",
            name="uq_chat_thread_reads_thread_key",
        ),
    )
