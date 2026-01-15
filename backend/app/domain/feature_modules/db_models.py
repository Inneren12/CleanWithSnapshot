from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base, UUID_TYPE


class OrgFeatureConfig(Base):
    __tablename__ = "org_feature_configs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("organizations.org_id", ondelete="CASCADE"), primary_key=True
    )
    feature_overrides: Mapped[dict] = mapped_column(
        sa.JSON(), default=dict, server_default=sa.text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )


class UserUiPreference(Base):
    __tablename__ = "user_ui_preferences"
    __table_args__ = (
        sa.UniqueConstraint("org_id", "user_key", name="uq_user_ui_prefs_org_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, sa.ForeignKey("organizations.org_id", ondelete="CASCADE")
    )
    user_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    hidden_keys: Mapped[list[str]] = mapped_column(
        sa.JSON(), default=list, server_default=sa.text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )
