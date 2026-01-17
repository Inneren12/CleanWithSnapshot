from __future__ import annotations

import uuid
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
