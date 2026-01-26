import uuid
from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base, UUID_TYPE


class BreakGlassScope(str, Enum):
    ORG = "org"
    GLOBAL = "global"


class BreakGlassStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class BreakGlassSession(Base):
    __tablename__ = "break_glass_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    actor: Mapped[str] = mapped_column(sa.String(150), nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    incident_ref: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    scope: Mapped[str] = mapped_column(
        sa.Enum(BreakGlassScope, name="breakglassscope"),
        nullable=False,
        default=BreakGlassScope.ORG,
    )
    status: Mapped[str] = mapped_column(
        sa.Enum(BreakGlassStatus, name="breakglassstatus"),
        nullable=False,
        default=BreakGlassStatus.ACTIVE,
    )
    token_hash: Mapped[str] = mapped_column(sa.String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(sa.String(128))
    review_notes: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    __table_args__ = (
        sa.Index("ix_break_glass_sessions_org", "org_id"),
        sa.Index("ix_break_glass_sessions_org_expires", "org_id", "expires_at"),
        sa.Index("ix_break_glass_sessions_status", "status"),
    )
