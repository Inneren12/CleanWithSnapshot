from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications_center import db_models

URGENT_PRIORITIES = {"CRITICAL", "HIGH"}


def _encode_cursor(created_at: datetime, event_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{event_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        created_raw, event_raw = decoded.split("|", 1)
        created_at = datetime.fromisoformat(created_raw)
        event_id = uuid.UUID(event_raw)
    except Exception:  # noqa: BLE001
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at, event_id


def _apply_cursor(stmt: sa.Select, cursor: str | None) -> sa.Select:
    parsed = _decode_cursor(cursor) if cursor else None
    if not parsed:
        return stmt
    created_at, event_id = parsed
    return stmt.where(
        sa.or_(
            db_models.NotificationEvent.created_at < created_at,
            sa.and_(
                db_models.NotificationEvent.created_at == created_at,
                db_models.NotificationEvent.id < event_id,
            ),
        )
    )


async def list_notifications(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_key: str,
    filter_key: str,
    limit: int,
    cursor: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
) -> tuple[list[db_models.NotificationEvent], dict[uuid.UUID, datetime], str | None]:
    reads_subq = (
        sa.select(
            db_models.NotificationRead.event_id.label("event_id"),
            db_models.NotificationRead.read_at.label("read_at"),
        )
        .where(
            db_models.NotificationRead.org_id == org_id,
            db_models.NotificationRead.user_id == user_key,
        )
        .subquery()
    )

    stmt = (
        sa.select(db_models.NotificationEvent, reads_subq.c.read_at)
        .outerjoin(reads_subq, db_models.NotificationEvent.id == reads_subq.c.event_id)
        .where(db_models.NotificationEvent.org_id == org_id)
    )

    if from_ts:
        stmt = stmt.where(db_models.NotificationEvent.created_at >= from_ts)
    if to_ts:
        stmt = stmt.where(db_models.NotificationEvent.created_at <= to_ts)

    normalized_filter = filter_key.lower().strip()
    if normalized_filter == "urgent":
        stmt = stmt.where(db_models.NotificationEvent.priority.in_(sorted(URGENT_PRIORITIES)))
    elif normalized_filter == "unread":
        stmt = stmt.where(reads_subq.c.event_id.is_(None))

    stmt = _apply_cursor(stmt, cursor)

    stmt = stmt.order_by(
        sa.desc(db_models.NotificationEvent.created_at),
        sa.desc(db_models.NotificationEvent.id),
    ).limit(limit)

    result = await session.execute(stmt)
    rows = result.all()

    read_map: dict[uuid.UUID, datetime] = {}
    events: list[db_models.NotificationEvent] = []
    for event, read_at in rows:
        events.append(event)
        if read_at:
            read_map[event.id] = read_at

    next_cursor = None
    if events and len(events) == limit:
        tail = events[-1]
        next_cursor = _encode_cursor(tail.created_at, tail.id)

    return events, read_map, next_cursor


async def mark_notification_read(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_key: str,
    event_id: uuid.UUID,
) -> db_models.NotificationRead:
    read_record = await session.scalar(
        sa.select(db_models.NotificationRead).where(
            db_models.NotificationRead.org_id == org_id,
            db_models.NotificationRead.user_id == user_key,
            db_models.NotificationRead.event_id == event_id,
        )
    )
    if read_record:
        return read_record

    read_record = db_models.NotificationRead(
        org_id=org_id,
        user_id=user_key,
        event_id=event_id,
        read_at=datetime.now(timezone.utc),
    )
    session.add(read_record)
    await session.flush()
    return read_record


async def mark_all_notifications_read(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_key: str,
) -> int:
    read_subq = (
        sa.select(db_models.NotificationRead.event_id)
        .where(
            db_models.NotificationRead.org_id == org_id,
            db_models.NotificationRead.user_id == user_key,
        )
        .subquery()
    )
    event_ids = await session.scalars(
        sa.select(db_models.NotificationEvent.id)
        .where(
            db_models.NotificationEvent.org_id == org_id,
            ~db_models.NotificationEvent.id.in_(sa.select(read_subq.c.event_id)),
        )
    )
    event_list = list(event_ids)
    if not event_list:
        return 0

    now = datetime.now(timezone.utc)
    for event_id in event_list:
        session.add(
            db_models.NotificationRead(
                org_id=org_id,
                user_id=user_key,
                event_id=event_id,
                read_at=now,
            )
        )
    await session.flush()
    return len(event_list)


def parse_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    return _decode_cursor(cursor) if cursor else None
