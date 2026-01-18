from __future__ import annotations

import uuid
from typing import Iterable
from urllib.parse import urlencode

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.integrations.db_models import AccountingSyncState, IntegrationsAccountingAccount
from app.settings import settings

QBO_PROVIDER = "quickbooks"
QBO_SCOPES = ["com.intuit.quickbooks.accounting"]
QBO_AUTH_BASE_URL = "https://appcenter.intuit.com/connect/oauth2"
QBO_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
TOKEN_EXCHANGE_TRANSPORT: httpx.AsyncBaseTransport | None = None


def oauth_configured() -> bool:
    return bool(
        settings.quickbooks_oauth_client_id
        and settings.quickbooks_oauth_client_secret
        and settings.quickbooks_oauth_redirect_uri
    )


def build_auth_url(*, state: str | None = None, scopes: Iterable[str] | None = None) -> str:
    scope_value = " ".join(scopes or QBO_SCOPES)
    query = {
        "client_id": settings.quickbooks_oauth_client_id,
        "redirect_uri": settings.quickbooks_oauth_redirect_uri,
        "response_type": "code",
        "scope": scope_value,
    }
    if state:
        query["state"] = state
    return f"{QBO_AUTH_BASE_URL}?{urlencode(query)}"


async def exchange_code_for_refresh_token(code: str) -> str:
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.quickbooks_oauth_redirect_uri,
    }
    timeout = httpx.Timeout(10.0, connect=5.0)
    auth = httpx.BasicAuth(settings.quickbooks_oauth_client_id or "", settings.quickbooks_oauth_client_secret or "")
    async with httpx.AsyncClient(timeout=timeout, transport=TOKEN_EXCHANGE_TRANSPORT) as client:
        response = await client.post(QBO_TOKEN_URL, data=payload, auth=auth)
    if response.status_code != 200:
        raise ValueError("token_exchange_failed")
    data = response.json()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise ValueError("missing_refresh_token")
    return refresh_token


async def get_account(
    session: AsyncSession, org_id: uuid.UUID
) -> IntegrationsAccountingAccount | None:
    return await session.get(
        IntegrationsAccountingAccount,
        {"org_id": org_id, "provider": QBO_PROVIDER},
    )


async def upsert_account(
    session: AsyncSession,
    org_id: uuid.UUID,
    refresh_token: str,
    realm_id: str,
) -> IntegrationsAccountingAccount:
    account = await get_account(session, org_id)
    if account:
        account.encrypted_refresh_token = refresh_token
        account.realm_id = realm_id
        return account
    account = IntegrationsAccountingAccount(
        org_id=org_id,
        provider=QBO_PROVIDER,
        encrypted_refresh_token=refresh_token,
        realm_id=realm_id,
    )
    session.add(account)
    return account


async def get_sync_state(
    session: AsyncSession, org_id: uuid.UUID
) -> AccountingSyncState | None:
    return await session.get(
        AccountingSyncState,
        {"org_id": org_id, "provider": QBO_PROVIDER},
    )


async def disconnect_quickbooks(session: AsyncSession, org_id: uuid.UUID) -> None:
    await session.execute(
        sa.delete(IntegrationsAccountingAccount).where(
            IntegrationsAccountingAccount.org_id == org_id,
            IntegrationsAccountingAccount.provider == QBO_PROVIDER,
        )
    )
    await session.execute(
        sa.delete(AccountingSyncState).where(
            AccountingSyncState.org_id == org_id,
            AccountingSyncState.provider == QBO_PROVIDER,
        )
    )
