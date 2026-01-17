from __future__ import annotations

import uuid
from datetime import datetime, time, timezone
from typing import Iterable
from urllib.parse import urlencode

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.integrations.db_models import (
    IntegrationsGcalCalendar,
    IntegrationsGcalEventMap,
    IntegrationsGcalSyncState,
    IntegrationsGoogleAccount,
    ScheduleExternalBlock,
)
from app.settings import settings

GCAL_SCOPES = ["https://www.googleapis.com/auth/calendar"]
GCAL_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GCAL_TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKEN_EXCHANGE_TRANSPORT: httpx.AsyncBaseTransport | None = None


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
) -> IntegrationsGoogleAccount:
    account = await get_google_account(session, org_id)
    if account:
        account.encrypted_refresh_token = refresh_token
        account.token_scopes = scopes
        return account
    account = IntegrationsGoogleAccount(
        org_id=org_id,
        encrypted_refresh_token=refresh_token,
        token_scopes=scopes,
    )
    session.add(account)
    return account


async def get_primary_calendar_id(session: AsyncSession, org_id: uuid.UUID) -> str | None:
    return await session.scalar(
        sa.select(IntegrationsGcalCalendar.calendar_id)
        .where(IntegrationsGcalCalendar.org_id == org_id)
        .limit(1)
    )


async def disconnect_google_calendar(session: AsyncSession, org_id: uuid.UUID) -> None:
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


async def import_external_blocks(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    starts_at: datetime,
    ends_at: datetime,
) -> int:
    account = await get_google_account(session, org_id)
    if account is None:
        raise ValueError("gcal_not_connected")
    calendar_id = await get_primary_calendar_id(session, org_id)
    if not calendar_id:
        raise ValueError("gcal_calendar_missing")

    access_token = await _refresh_access_token(account.encrypted_refresh_token)
    events = await _fetch_calendar_events(access_token, calendar_id, starts_at, ends_at)

    imported = 0
    for event in events:
        event_id = event.get("id")
        if not event_id:
            continue
        window = _event_window(event)
        if window is None:
            continue
        start, end = window
        if end <= start:
            continue
        summary = event.get("summary")
        stmt = _external_block_insert(session).values(
            org_id=org_id,
            source="gcal",
            external_event_id=event_id,
            starts_at=start,
            ends_at=end,
            summary=summary,
        )
        upsert = stmt.on_conflict_do_update(
            index_elements=[ScheduleExternalBlock.org_id, ScheduleExternalBlock.external_event_id],
            set_={
                "starts_at": start,
                "ends_at": end,
                "summary": summary,
                "source": "gcal",
                "updated_at": sa.func.now(),
            },
        )
        await session.execute(upsert)
        imported += 1

    await _upsert_sync_state(session, org_id, calendar_id, last_error=None)
    return imported


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _refresh_access_token(refresh_token: str) -> str:
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


async def _fetch_calendar_events(
    access_token: str,
    calendar_id: str,
    starts_at: datetime,
    ends_at: datetime,
) -> list[dict]:
    base_url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "timeMin": _normalize_datetime(starts_at).isoformat(),
        "timeMax": _normalize_datetime(ends_at).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    timeout = httpx.Timeout(10.0, connect=5.0)
    items: list[dict] = []
    page_token: str | None = None

    async with httpx.AsyncClient(timeout=timeout, transport=TOKEN_EXCHANGE_TRANSPORT) as client:
        while True:
            if page_token:
                params["pageToken"] = page_token
            response = await client.get(base_url, headers=headers, params=params)
            if response.status_code != 200:
                raise ValueError("gcal_events_fetch_failed")
            payload = response.json()
            for event in payload.get("items", []) or []:
                if event.get("status") == "cancelled":
                    continue
                items.append(event)
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
    return items


def _event_window(event: dict) -> tuple[datetime, datetime] | None:
    start_payload = event.get("start") or {}
    end_payload = event.get("end") or {}
    start_value = start_payload.get("dateTime") or start_payload.get("date")
    end_value = end_payload.get("dateTime") or end_payload.get("date")
    if not start_value or not end_value:
        return None
    start = _parse_event_datetime(start_value)
    end = _parse_event_datetime(end_value)
    return start, end


def _parse_event_datetime(value: str) -> datetime:
    if "T" in value:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return _normalize_datetime(parsed)
    parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)


def _external_block_insert(session: AsyncSession):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        return insert(ScheduleExternalBlock)
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert

        return insert(ScheduleExternalBlock)
    return sa.insert(ScheduleExternalBlock)


async def _upsert_sync_state(
    session: AsyncSession,
    org_id: uuid.UUID,
    calendar_id: str,
    *,
    last_error: str | None,
) -> None:
    stmt = _sync_state_insert(session).values(
        org_id=org_id,
        calendar_id=calendar_id,
        last_sync_at=sa.func.now(),
        last_error=last_error,
    )
    upsert = stmt.on_conflict_do_update(
        index_elements=[IntegrationsGcalSyncState.org_id, IntegrationsGcalSyncState.calendar_id],
        set_={"last_sync_at": sa.func.now(), "last_error": last_error},
    )
    await session.execute(upsert)


def _sync_state_insert(session: AsyncSession):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        return insert(IntegrationsGcalSyncState)
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert

        return insert(IntegrationsGcalSyncState)
    return sa.insert(IntegrationsGcalSyncState)
