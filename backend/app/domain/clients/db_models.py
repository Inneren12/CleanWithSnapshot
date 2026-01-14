import json
import uuid
from datetime import datetime
from typing import Iterable

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import UUID_TYPE, Base
from app.settings import settings


def normalize_tags(raw: Iterable[str] | str | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        candidates = [part.strip() for part in raw.split(",")]
    else:
        candidates = [str(item).strip() for item in raw]
    seen: set[str] = set()
    normalized: list[str] = []
    for tag in candidates:
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(tag)
    return normalized


def parse_tags_json(tags_json: str | None) -> list[str]:
    if not tags_json:
        return []
    try:
        data = json.loads(tags_json)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return normalize_tags([str(item) for item in data])
    return normalize_tags([str(data)])


class ClientUser(Base):
    __tablename__ = "client_users"

    client_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text())
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    is_blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    tags_json: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_client_users_org_id", "org_id"),)


class ClientNote(Base):
    __tablename__ = "client_notes"

    NOTE_TYPE_NOTE = "NOTE"
    NOTE_TYPE_COMPLAINT = "COMPLAINT"
    NOTE_TYPE_PRAISE = "PRAISE"
    NOTE_TYPES = {
        NOTE_TYPE_NOTE,
        NOTE_TYPE_COMPLAINT,
        NOTE_TYPE_PRAISE,
    }

    note_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    client_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("client_users.client_id", ondelete="CASCADE"),
        nullable=False,
    )
    note_text: Mapped[str] = mapped_column(Text(), nullable=False)
    note_type: Mapped[str] = mapped_column(
        Text(),
        nullable=False,
        server_default=NOTE_TYPE_NOTE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        Index("ix_client_notes_org_id", "org_id"),
        Index("ix_client_notes_client_id", "client_id"),
    )


def normalize_note_type(raw: str | None) -> str:
    if not raw:
        return ClientNote.NOTE_TYPE_NOTE
    normalized = str(raw).strip().upper()
    if normalized in ClientNote.NOTE_TYPES:
        return normalized
    raise ValueError("Invalid note type")
