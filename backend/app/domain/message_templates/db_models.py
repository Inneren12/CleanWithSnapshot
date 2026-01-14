from __future__ import annotations

from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base, UUID_TYPE


class MessageTemplate(Base):
    __tablename__ = "message_templates"

    template_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (
        sa.Index("ix_message_templates_org_id", "org_id"),
        sa.UniqueConstraint("org_id", "name", name="uq_message_templates_org_name"),
    )
