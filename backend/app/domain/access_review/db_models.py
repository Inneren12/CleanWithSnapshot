from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base, UUID_TYPE


class AccessReviewRun(Base):
    __tablename__ = "access_review_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, sa.ForeignKey("organizations.org_id", ondelete="SET NULL"), nullable=True
    )
    scope: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    run_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    generated_by: Mapped[str] = mapped_column(sa.String(150), nullable=False)
    artifact_hash: Mapped[str] = mapped_column(sa.String(128), nullable=False)

    __table_args__ = (
        sa.Index("ix_access_review_runs_org_scope", "org_id", "scope"),
        sa.Index("ix_access_review_runs_run_at", "run_at"),
    )
