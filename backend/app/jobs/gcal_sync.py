from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feature_modules import service as feature_service
from app.domain.integrations import gcal_service
from app.domain.integrations.db_models import (
    GcalSyncMode,
    IntegrationsGcalCalendar,
    IntegrationsGcalSyncState,
)
from app.settings import settings

logger = logging.getLogger(__name__)


def _parse_cursor(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


async def _ensure_sync_state(
    session: AsyncSession, *, org_id: uuid.UUID, calendar_id: str
) -> IntegrationsGcalSyncState:
    state = await session.get(
        IntegrationsGcalSyncState,
        {"org_id": org_id, "calendar_id": calendar_id},
    )
    if state is None:
        state = IntegrationsGcalSyncState(
            org_id=org_id,
            calendar_id=calendar_id,
            sync_cursor=None,
            last_sync_at=None,
            last_error=None,
        )
        session.add(state)
        await session.flush()
    return state


def _should_run(state: IntegrationsGcalSyncState | None, *, now: datetime) -> bool:
    if not state or not state.last_sync_at:
        return True
    interval_seconds = max(settings.gcal_sync_interval_seconds, 1)
    last_sync_at = state.last_sync_at
    if last_sync_at.tzinfo is None:
        last_sync_at = last_sync_at.replace(tzinfo=timezone.utc)
    return (now - last_sync_at).total_seconds() >= interval_seconds


def _sync_window(state: IntegrationsGcalSyncState | None, *, now: datetime) -> tuple[datetime, datetime]:
    cursor = _parse_cursor(state.sync_cursor) if state else None
    if cursor is None:
        cursor = now - timedelta(days=settings.gcal_sync_initial_days)
    from_date = cursor - timedelta(minutes=settings.gcal_sync_backfill_minutes)
    to_date = now + timedelta(days=settings.gcal_sync_future_days)
    return from_date, to_date


async def run_gcal_sync(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.now(tz=timezone.utc)
    calendars_stmt = sa.select(IntegrationsGcalCalendar)
    if org_id:
        calendars_stmt = calendars_stmt.where(IntegrationsGcalCalendar.org_id == org_id)
    calendars = (await session.scalars(calendars_stmt)).all()
    if not calendars:
        return {"processed": 0, "skipped": 1, "errors": 0}

    processed = 0
    skipped = 0
    errors = 0
    for calendar in calendars:
        module_enabled = await feature_service.effective_feature_enabled(
            session, calendar.org_id, "module.integrations"
        )
        gcal_enabled = await feature_service.effective_feature_enabled(
            session, calendar.org_id, "integrations.google_calendar"
        )
        if not (module_enabled and gcal_enabled):
            skipped += 1
            continue
        account = await gcal_service.get_google_account(session, calendar.org_id)
        if not account:
            skipped += 1
            continue

        state = await _ensure_sync_state(
            session, org_id=calendar.org_id, calendar_id=calendar.calendar_id
        )
        if not _should_run(state, now=now):
            skipped += 1
            continue

        from_date, to_date = _sync_window(state, now=now)
        try:
            if calendar.mode in {GcalSyncMode.EXPORT, GcalSyncMode.TWO_WAY}:
                await gcal_service.export_bookings_to_gcal(
                    session,
                    calendar.org_id,
                    from_date=from_date,
                    to_date=to_date,
                )
            if calendar.mode in {GcalSyncMode.IMPORT, GcalSyncMode.TWO_WAY}:
                await gcal_service.import_gcal_events_to_blocks(
                    session,
                    calendar.org_id,
                    from_date=from_date,
                    to_date=to_date,
                )
            state.last_sync_at = now
            state.sync_cursor = now.isoformat()
            state.last_error = None
            await session.commit()
            processed += 1
        except Exception as exc:  # noqa: BLE001
            state.last_sync_at = now
            state.last_error = str(exc) or type(exc).__name__
            await session.commit()
            logger.warning(
                "gcal_sync_failed",
                extra={
                    "extra": {
                        "org_id": str(calendar.org_id),
                        "calendar_id": calendar.calendar_id,
                        "reason": type(exc).__name__,
                    }
                },
            )
            errors += 1

    return {"processed": processed, "skipped": skipped, "errors": errors}
