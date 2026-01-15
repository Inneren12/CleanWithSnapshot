from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base, UUID_TYPE


class IamRole(Base):
    __tablename__ = "iam_roles"
    __table_args__ = (
        sa.UniqueConstraint("org_id", "role_key", name="uq_iam_roles_org_key"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_key: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.String(255))
    permissions: Mapped[list[str]] = mapped_column(sa.JSON(), nullable=False, default=list, server_default=sa.text("'[]'"))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )
