from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feature_modules import service as feature_service
from app.domain.notifications_center import db_models

PRESET_KEYS = [
    "no_show",
    "payment_failed",
    "negative_review",
    "low_stock",
    "high_value_lead",
]

DEFAULT_PRESET = {
    "enabled": False,
    "notify_roles": [],
    "notify_user_ids": [],
    "escalation_delay_min": None,
}

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


async def list_urgent_unread_notifications(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_key: str,
    limit: int,
) -> list[db_models.NotificationEvent]:
    reads_subq = (
        sa.select(db_models.NotificationRead.event_id.label("event_id"))
        .where(
            db_models.NotificationRead.org_id == org_id,
            db_models.NotificationRead.user_id == user_key,
        )
        .subquery()
    )

    stmt = (
        sa.select(db_models.NotificationEvent)
        .outerjoin(reads_subq, db_models.NotificationEvent.id == reads_subq.c.event_id)
        .where(
            db_models.NotificationEvent.org_id == org_id,
            db_models.NotificationEvent.priority.in_(sorted(URGENT_PRIORITIES)),
            reads_subq.c.event_id.is_(None),
        )
        .order_by(
            sa.desc(db_models.NotificationEvent.created_at),
            sa.desc(db_models.NotificationEvent.id),
        )
        .limit(limit)
    )

    result = await session.execute(stmt)
    return list(result.scalars())


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


def _normalize_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _default_preset_record(
    org_id: uuid.UUID, preset_key: str
) -> db_models.NotificationRulePreset:
    return db_models.NotificationRulePreset(
        org_id=org_id,
        preset_key=preset_key,
        enabled=DEFAULT_PRESET["enabled"],
        notify_roles=list(DEFAULT_PRESET["notify_roles"]),
        notify_user_ids=list(DEFAULT_PRESET["notify_user_ids"]),
        escalation_delay_min=DEFAULT_PRESET["escalation_delay_min"],
    )


async def list_rule_presets(
    session: AsyncSession, *, org_id: uuid.UUID
) -> list[db_models.NotificationRulePreset]:
    rows = await session.execute(
        sa.select(db_models.NotificationRulePreset).where(
            db_models.NotificationRulePreset.org_id == org_id
        )
    )
    existing = {row.preset_key: row for row in rows.scalars()}
    presets: list[db_models.NotificationRulePreset] = []
    for key in PRESET_KEYS:
        presets.append(existing.get(key) or _default_preset_record(org_id, key))
    return presets


async def upsert_rule_presets(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    updates: list[dict],
) -> list[db_models.NotificationRulePreset]:
    keys = [update.get("preset_key") for update in updates or [] if update.get("preset_key")]
    if not keys:
        return await list_rule_presets(session, org_id=org_id)

    rows = await session.execute(
        sa.select(db_models.NotificationRulePreset).where(
            db_models.NotificationRulePreset.org_id == org_id,
            db_models.NotificationRulePreset.preset_key.in_(keys),
        )
    )
    existing = {row.preset_key: row for row in rows.scalars()}

    for payload in updates:
        preset_key = payload.get("preset_key")
        if not preset_key:
            continue
        record = existing.get(preset_key)
        if record is None:
            record = _default_preset_record(org_id, preset_key)
            session.add(record)
            existing[preset_key] = record
        if "enabled" in payload and payload["enabled"] is not None:
            record.enabled = bool(payload["enabled"])
        if "notify_roles" in payload and payload["notify_roles"] is not None:
            record.notify_roles = _normalize_list(payload["notify_roles"])
        if "notify_user_ids" in payload and payload["notify_user_ids"] is not None:
            record.notify_user_ids = _normalize_list(payload["notify_user_ids"])
        if "escalation_delay_min" in payload:
            record.escalation_delay_min = payload["escalation_delay_min"]
    await session.flush()
    return await list_rule_presets(session, org_id=org_id)


async def emit_preset_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    preset_key: str,
    priority: str,
    title: str,
    body: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action_href: str | None = None,
    action_kind: str | None = None,
) -> db_models.NotificationEvent | None:
    if preset_key not in PRESET_KEYS:
        raise ValueError("Unknown preset key")
    enabled = await feature_service.effective_feature_enabled(
        session, org_id, "module.notifications_center"
    )
    if not enabled:
        return None

    preset = await session.scalar(
        sa.select(db_models.NotificationRulePreset).where(
            db_models.NotificationRulePreset.org_id == org_id,
            db_models.NotificationRulePreset.preset_key == preset_key,
        )
    )
    if preset is None:
        preset = _default_preset_record(org_id, preset_key)
    if not preset.enabled:
        return None

    event = db_models.NotificationEvent(
        org_id=org_id,
        priority=priority,
        type=preset_key,
        title=title,
        body=body,
        entity_type=entity_type,
        entity_id=entity_id,
        action_href=action_href,
        action_kind=action_kind,
    )
    session.add(event)
    await session.flush()
    return event
