from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import BLOCKING_STATUSES
from app.domain.config_audit import ConfigAuditActor
from app.domain.integrations.db_models import (
    GcalSyncMode,
    IntegrationsGcalCalendar,
    IntegrationsGcalEventMap,
    IntegrationsGcalSyncState,
    IntegrationsGoogleAccount,
    ScheduleExternalBlock,
)
from app.domain.integration_audit import IntegrationAuditContext, IntegrationScope
from app.domain.integration_audit import service as integration_audit_service
from app.domain.org_settings import service as org_settings_service
from app.settings import settings

GCAL_SCOPES = ["https://www.googleapis.com/auth/calendar"]
GCAL_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GCAL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GCAL_API_BASE_URL = "https://www.googleapis.com/calendar/v3"
TOKEN_EXCHANGE_TRANSPORT: httpx.AsyncBaseTransport | None = None
GCAL_API_TRANSPORT: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True)
class GcalExportSyncResult:
    calendar_id: str
    from_utc: datetime
    to_utc: datetime
    created: int
    updated: int
    skipped: int

    @property
    def total(self) -> int:
        return self.created + self.updated + self.skipped


@dataclass(frozen=True)
class GcalImportSyncResult:
    calendar_id: str
    from_utc: datetime
    to_utc: datetime
    created: int
    updated: int
    skipped: int

    @property
    def total(self) -> int:
        return self.created + self.updated + self.skipped


class GcalClient:
    def __init__(self, access_token: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=GCAL_API_BASE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=httpx.Timeout(15.0, connect=5.0),
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def create_event(self, calendar_id: str, payload: dict) -> dict:
        response = await self._client.post(f"/calendars/{calendar_id}/events", json=payload)
        if response.status_code >= 400:
            raise ValueError("gcal_event_create_failed")
        return response.json()

    async def update_event(self, calendar_id: str, event_id: str, payload: dict) -> dict:
        response = await self._client.put(f"/calendars/{calendar_id}/events/{event_id}", json=payload)
        if response.status_code >= 400:
            raise ValueError("gcal_event_update_failed")
        return response.json()

    async def list_events(
        self,
        calendar_id: str,
        *,
        time_min: datetime,
        time_max: datetime,
    ) -> list[dict]:
        events: list[dict] = []
        page_token: str | None = None
        while True:
            params = {
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
            }
            if page_token:
                params["pageToken"] = page_token
            response = await self._client.get(f"/calendars/{calendar_id}/events", params=params)
            if response.status_code >= 400:
                raise ValueError("gcal_event_list_failed")
            payload = response.json()
            events.extend(payload.get("items", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return events


GCAL_CLIENT_FACTORY: Callable[[str], GcalClient] = (
    lambda access_token: GcalClient(access_token, transport=GCAL_API_TRANSPORT)
)


def oauth_configured() -> bool:
    return bool(
        settings.google_oauth_client_id
        and settings.google_oauth_client_secret
        and settings.google_oauth_redirect_uri
    )


def build_auth_url(*, state: str | None = None, scopes: Iterable[str] | None = None) -> str:
    scope_value = " ".join(scopes or GCAL_SCOPES)
    query = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "scope": scope_value,
    }
    if state:
        query["state"] = state
    return f"{GCAL_AUTH_BASE_URL}?{urlencode(query)}"


async def exchange_code_for_refresh_token(code: str) -> tuple[str, list[str]]:
    payload = {
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "grant_type": "authorization_code",
        "code": code,
    }
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout, transport=TOKEN_EXCHANGE_TRANSPORT) as client:
        response = await client.post(GCAL_TOKEN_URL, data=payload)
    if response.status_code != 200:
        raise ValueError("token_exchange_failed")
    data = response.json()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise ValueError("missing_refresh_token")
    scope_value = data.get("scope")
    scopes = [scope for scope in (scope_value or "").split() if scope]
    return refresh_token, scopes


async def exchange_refresh_token_for_access_token(refresh_token: str) -> str:
    payload = {
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout, transport=TOKEN_EXCHANGE_TRANSPORT) as client:
        response = await client.post(GCAL_TOKEN_URL, data=payload)
    if response.status_code != 200:
        raise ValueError("access_token_exchange_failed")
    data = response.json()
    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("missing_access_token")
    return access_token


async def get_google_account(
    session: AsyncSession, org_id: uuid.UUID
) -> IntegrationsGoogleAccount | None:
    return await session.scalar(
        sa.select(IntegrationsGoogleAccount).where(IntegrationsGoogleAccount.org_id == org_id)
    )


async def upsert_google_account(
    session: AsyncSession,
    org_id: uuid.UUID,
    refresh_token: str,
    scopes: list[str],
    *,
    audit_actor: ConfigAuditActor,
    request_id: str | None,
) -> IntegrationsGoogleAccount:
    account = await get_google_account(session, org_id)
    before_snapshot = await _snapshot_google_integration(session, org_id)
    if account:
        account.encrypted_refresh_token = refresh_token
        account.token_scopes = scopes
        await session.flush()
        after_snapshot = await _snapshot_google_integration(session, org_id)
        await integration_audit_service.audit_integration_config_change(
            session,
            actor=audit_actor,
            org_id=org_id,
            context=IntegrationAuditContext(
                integration_type="google_calendar",
                integration_scope=IntegrationScope.ORG,
            ),
            before_state=before_snapshot,
            after_state=after_snapshot,
            request_id=request_id,
        )
        return account
    account = IntegrationsGoogleAccount(
        org_id=org_id,
        encrypted_refresh_token=refresh_token,
        token_scopes=scopes,
    )
    session.add(account)
    await session.flush()
    after_snapshot = await _snapshot_google_integration(session, org_id)
    await integration_audit_service.audit_integration_config_change(
        session,
        actor=audit_actor,
        org_id=org_id,
        context=IntegrationAuditContext(
            integration_type="google_calendar",
            integration_scope=IntegrationScope.ORG,
        ),
        before_state=before_snapshot,
        after_state=after_snapshot,
        request_id=request_id,
    )
    return account


async def get_primary_calendar_id(session: AsyncSession, org_id: uuid.UUID) -> str | None:
    return await session.scalar(
        sa.select(IntegrationsGcalCalendar.calendar_id)
        .where(IntegrationsGcalCalendar.org_id == org_id)
        .limit(1)
    )


async def get_sync_state(
    session: AsyncSession, org_id: uuid.UUID, calendar_id: str
) -> IntegrationsGcalSyncState | None:
    return await session.get(
        IntegrationsGcalSyncState,
        {"org_id": org_id, "calendar_id": calendar_id},
    )


async def get_export_calendar(session: AsyncSession, org_id: uuid.UUID) -> IntegrationsGcalCalendar | None:
    return await session.scalar(
        sa.select(IntegrationsGcalCalendar).where(
            IntegrationsGcalCalendar.org_id == org_id,
            IntegrationsGcalCalendar.mode.in_([GcalSyncMode.EXPORT, GcalSyncMode.TWO_WAY]),
        )
    )


async def get_import_calendar(session: AsyncSession, org_id: uuid.UUID) -> IntegrationsGcalCalendar | None:
    return await session.scalar(
        sa.select(IntegrationsGcalCalendar).where(
            IntegrationsGcalCalendar.org_id == org_id,
            IntegrationsGcalCalendar.mode.in_([GcalSyncMode.IMPORT, GcalSyncMode.TWO_WAY]),
        )
    )


async def disconnect_google_calendar(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    audit_actor: ConfigAuditActor,
    request_id: str | None,
) -> None:
    before_snapshot = await _snapshot_google_integration(session, org_id)
    await session.execute(
        sa.delete(IntegrationsGoogleAccount).where(IntegrationsGoogleAccount.org_id == org_id)
    )
    await session.execute(
        sa.delete(IntegrationsGcalCalendar).where(IntegrationsGcalCalendar.org_id == org_id)
    )
    await session.execute(
        sa.delete(IntegrationsGcalSyncState).where(IntegrationsGcalSyncState.org_id == org_id)
    )
    await session.execute(
        sa.delete(IntegrationsGcalEventMap).where(IntegrationsGcalEventMap.org_id == org_id)
    )
    await session.execute(
        sa.delete(ScheduleExternalBlock).where(
            ScheduleExternalBlock.org_id == org_id,
            ScheduleExternalBlock.source == "gcal",
        )
    )
    await session.flush()
    await integration_audit_service.audit_integration_config_change(
        session,
        actor=audit_actor,
        org_id=org_id,
        context=IntegrationAuditContext(
            integration_type="google_calendar",
            integration_scope=IntegrationScope.ORG,
        ),
        before_state=before_snapshot,
        after_state=None,
        request_id=request_id,
    )


async def _snapshot_google_integration(session: AsyncSession, org_id: uuid.UUID) -> dict[str, object | None]:
    account = await get_google_account(session, org_id)
    calendars = await session.scalars(
        sa.select(IntegrationsGcalCalendar).where(IntegrationsGcalCalendar.org_id == org_id)
    )
    calendar_entries = [
        {"calendar_id": calendar.calendar_id, "mode": calendar.mode.value} for calendar in calendars
    ]
    return {
        "connected": bool(account),
        "provider": account.provider if account else None,
        "encrypted_refresh_token": account.encrypted_refresh_token if account else None,
        "token_scopes": account.token_scopes if account else None,
        "calendars": calendar_entries,
    }


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _booking_end(booking: Booking) -> datetime:
    return _ensure_aware(booking.starts_at) + timedelta(minutes=booking.duration_minutes)


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _parse_event_datetime(payload: dict, *, default_tz: ZoneInfo) -> datetime | None:
    date_time = payload.get("dateTime")
    if isinstance(date_time, str):
        parsed = _parse_iso_datetime(date_time)
        if parsed.tzinfo is None:
            tz_name = payload.get("timeZone")
            tzinfo = ZoneInfo(tz_name) if tz_name else default_tz
            parsed = parsed.replace(tzinfo=tzinfo)
        return parsed
    date_value = payload.get("date")
    if isinstance(date_value, str):
        parsed_date = date.fromisoformat(date_value)
        tz_name = payload.get("timeZone")
        tzinfo = ZoneInfo(tz_name) if tz_name else default_tz
        return datetime.combine(parsed_date, datetime.min.time(), tzinfo=tzinfo)
    return None


def _event_time_range(event: dict, *, default_tz: ZoneInfo) -> tuple[datetime, datetime] | None:
    start = _parse_event_datetime(event.get("start", {}), default_tz=default_tz)
    end = _parse_event_datetime(event.get("end", {}), default_tz=default_tz)
    if not start or not end:
        return None
    normalized_start = _ensure_aware(start).astimezone(timezone.utc)
    normalized_end = _ensure_aware(end).astimezone(timezone.utc)
    if normalized_end <= normalized_start:
        return None
    return normalized_start, normalized_end


def _build_event_payload(booking: Booking, *, org_tz: str) -> dict:
    starts_at = _ensure_aware(booking.starts_at).astimezone(timezone.utc)
    ends_at = _booking_end(booking).astimezone(timezone.utc)
    description_lines = [
        f"Booking ID: {booking.booking_id}",
        f"Status: {booking.status}",
    ]
    return {
        "summary": f"Booking {booking.booking_id}",
        "description": "\n".join(description_lines),
        "start": {
            "dateTime": starts_at.isoformat(),
            "timeZone": org_tz,
        },
        "end": {
            "dateTime": ends_at.isoformat(),
            "timeZone": org_tz,
        },
    }


def _event_payload_hash(payload: dict) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def export_bookings_to_gcal(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: datetime,
    to_date: datetime,
) -> GcalExportSyncResult:
    account = await get_google_account(session, org_id)
    if not account:
        raise ValueError("missing_google_account")
    calendar = await get_export_calendar(session, org_id)
    if not calendar:
        raise ValueError("missing_google_calendar")
    settings_record = await org_settings_service.get_or_create_org_settings(session, org_id)
    org_tz = org_settings_service.resolve_timezone(settings_record)
    tzinfo = ZoneInfo(org_tz)
    from_utc = _ensure_aware(from_date).astimezone(timezone.utc)
    to_utc = _ensure_aware(to_date).astimezone(timezone.utc)
    if from_utc > to_utc:
        raise ValueError("invalid_date_range")

    bookings = (
        await session.scalars(
            sa.select(Booking)
            .where(
                Booking.org_id == org_id,
                Booking.archived_at.is_(None),
                Booking.status.in_(BLOCKING_STATUSES),
                Booking.starts_at >= from_utc,
                Booking.starts_at <= to_utc,
            )
            .order_by(Booking.starts_at.asc())
        )
    ).all()
    booking_ids = [booking.booking_id for booking in bookings]
    existing_maps: dict[str, IntegrationsGcalEventMap] = {}
    if booking_ids:
        rows = (
            await session.scalars(
                sa.select(IntegrationsGcalEventMap).where(
                    IntegrationsGcalEventMap.org_id == org_id,
                    IntegrationsGcalEventMap.calendar_id == calendar.calendar_id,
                    IntegrationsGcalEventMap.booking_id.in_(booking_ids),
                )
            )
        ).all()
        existing_maps = {row.booking_id: row for row in rows}

    access_token = await exchange_refresh_token_for_access_token(account.encrypted_refresh_token)
    client = GCAL_CLIENT_FACTORY(access_token)
    created = 0
    updated = 0
    skipped = 0
    try:
        for booking in bookings:
            payload = _build_event_payload(booking, org_tz=tzinfo.key)
            payload_hash = _event_payload_hash(payload)
            existing_map = existing_maps.get(booking.booking_id)
            if existing_map and existing_map.last_pushed_hash == payload_hash:
                skipped += 1
                continue
            if existing_map:
                response = await client.update_event(
                    calendar.calendar_id,
                    existing_map.external_event_id,
                    payload,
                )
                existing_map.external_event_id = response.get(
                    "id", existing_map.external_event_id
                )
                existing_map.last_pushed_hash = payload_hash
                updated += 1
            else:
                response = await client.create_event(calendar.calendar_id, payload)
                event_id = response.get("id")
                if not event_id:
                    raise ValueError("missing_event_id")
                new_map = IntegrationsGcalEventMap(
                    org_id=org_id,
                    booking_id=booking.booking_id,
                    calendar_id=calendar.calendar_id,
                    external_event_id=event_id,
                    last_pushed_hash=payload_hash,
                )
                session.add(new_map)
                created += 1
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result
    return GcalExportSyncResult(
        calendar_id=calendar.calendar_id,
        from_utc=from_utc,
        to_utc=to_utc,
        created=created,
        updated=updated,
        skipped=skipped,
    )


async def import_gcal_events_to_blocks(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: datetime,
    to_date: datetime,
) -> GcalImportSyncResult:
    account = await get_google_account(session, org_id)
    if not account:
        raise ValueError("missing_google_account")
    calendar = await get_import_calendar(session, org_id)
    if not calendar:
        raise ValueError("missing_google_calendar")
    settings_record = await org_settings_service.get_or_create_org_settings(session, org_id)
    org_tz = org_settings_service.resolve_timezone(settings_record)
    tzinfo = ZoneInfo(org_tz)
    from_utc = _ensure_aware(from_date).astimezone(timezone.utc)
    to_utc = _ensure_aware(to_date).astimezone(timezone.utc)
    if from_utc > to_utc:
        raise ValueError("invalid_date_range")

    access_token = await exchange_refresh_token_for_access_token(account.encrypted_refresh_token)
    client = GCAL_CLIENT_FACTORY(access_token)
    created = 0
    updated = 0
    skipped = 0
    try:
        events = await client.list_events(calendar.calendar_id, time_min=from_utc, time_max=to_utc)
        event_ids = [event.get("id") for event in events if event.get("id")]
        existing_blocks: dict[str, ScheduleExternalBlock] = {}
        if event_ids:
            rows = (
                await session.scalars(
                    sa.select(ScheduleExternalBlock).where(
                        ScheduleExternalBlock.org_id == org_id,
                        ScheduleExternalBlock.external_event_id.in_(event_ids),
                    )
                )
            ).all()
            existing_blocks = {row.external_event_id: row for row in rows}

        for event in events:
            if event.get("status") == "cancelled":
                skipped += 1
                continue
            external_event_id = event.get("id")
            if not external_event_id:
                skipped += 1
                continue
            time_range = _event_time_range(event, default_tz=tzinfo)
            if not time_range:
                skipped += 1
                continue
            starts_at, ends_at = time_range
            summary = event.get("summary")
            existing = existing_blocks.get(external_event_id)
            if existing:
                if (
                    existing.starts_at == starts_at
                    and existing.ends_at == ends_at
                    and existing.summary == summary
                ):
                    skipped += 1
                    continue
                existing.starts_at = starts_at
                existing.ends_at = ends_at
                existing.summary = summary
                updated += 1
            else:
                session.add(
                    ScheduleExternalBlock(
                        org_id=org_id,
                        source="gcal",
                        external_event_id=external_event_id,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        summary=summary,
                    )
                )
                created += 1
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result
    return GcalImportSyncResult(
        calendar_id=calendar.calendar_id,
        from_utc=from_utc,
        to_utc=to_utc,
        created=created,
        updated=updated,
        skipped=skipped,
    )
