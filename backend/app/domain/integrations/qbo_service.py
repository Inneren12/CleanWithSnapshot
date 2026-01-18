from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable, Iterable
from urllib.parse import urlencode

import httpx
import sqlalchemy as sa
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.integrations.db_models import AccountingInvoiceMap, AccountingSyncState, IntegrationsAccountingAccount
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice
from app.settings import settings

QBO_PROVIDER = "quickbooks"
QBO_SCOPES = ["com.intuit.quickbooks.accounting"]
QBO_AUTH_BASE_URL = "https://appcenter.intuit.com/connect/oauth2"
QBO_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QBO_API_BASE_URL = "https://quickbooks.api.intuit.com/v3/company"
TOKEN_EXCHANGE_TRANSPORT: httpx.AsyncBaseTransport | None = None
QBO_API_TRANSPORT: httpx.AsyncBaseTransport | None = None
QBO_PUSH_STATUSES = {
    invoice_statuses.INVOICE_STATUS_SENT,
    invoice_statuses.INVOICE_STATUS_PARTIAL,
    invoice_statuses.INVOICE_STATUS_OVERDUE,
}


@dataclass(frozen=True)
class QboInvoicePushResult:
    from_date: date
    to_date: date
    created: int
    updated: int
    skipped: int

    @property
    def total(self) -> int:
        return self.created + self.updated + self.skipped


@dataclass(frozen=True)
class QboInvoicePushItemResult:
    invoice_id: str
    remote_invoice_id: str | None
    action: str


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


async def exchange_refresh_token_for_access_token(refresh_token: str) -> tuple[str, str | None]:
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    timeout = httpx.Timeout(10.0, connect=5.0)
    auth = httpx.BasicAuth(settings.quickbooks_oauth_client_id or "", settings.quickbooks_oauth_client_secret or "")
    async with httpx.AsyncClient(timeout=timeout, transport=TOKEN_EXCHANGE_TRANSPORT) as client:
        response = await client.post(QBO_TOKEN_URL, data=payload, auth=auth)
    if response.status_code != 200:
        raise ValueError("access_token_exchange_failed")
    data = response.json()
    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("missing_access_token")
    new_refresh = data.get("refresh_token")
    return access_token, new_refresh


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


class QboClient:
    def __init__(
        self,
        access_token: str,
        realm_id: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._realm_id = realm_id
        self._client = httpx.AsyncClient(
            base_url=QBO_API_BASE_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=httpx.Timeout(15.0, connect=5.0),
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def create_invoice(self, payload: dict) -> dict:
        response = await self._client.post(f"/{self._realm_id}/invoice", json=payload)
        if response.status_code >= 400:
            raise ValueError("qbo_invoice_create_failed")
        data = response.json()
        return data.get("Invoice", data)

    async def get_invoice(self, invoice_id: str) -> dict:
        response = await self._client.get(f"/{self._realm_id}/invoice/{invoice_id}")
        if response.status_code >= 400:
            raise ValueError("qbo_invoice_fetch_failed")
        data = response.json()
        return data.get("Invoice", data)

    async def update_invoice(self, payload: dict) -> dict:
        response = await self._client.post(f"/{self._realm_id}/invoice", json=payload)
        if response.status_code >= 400:
            raise ValueError("qbo_invoice_update_failed")
        data = response.json()
        return data.get("Invoice", data)


QBO_CLIENT_FACTORY: Callable[[str, str], QboClient] = (
    lambda access_token, realm_id: QboClient(access_token, realm_id, transport=QBO_API_TRANSPORT)
)


def _cents_to_decimal(cents: int) -> str:
    value = (Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"))
    return f"{value:.2f}"


def _build_invoice_payload(invoice: Invoice) -> dict:
    line_items: list[dict] = []
    for item in invoice.items:
        unit_price = _cents_to_decimal(item.unit_price_cents)
        amount = _cents_to_decimal(item.line_total_cents)
        line_items.append(
            {
                "Description": item.description,
                "Amount": amount,
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {
                    "Qty": item.qty,
                    "UnitPrice": unit_price,
                },
            }
        )
    payload: dict = {
        "DocNumber": invoice.invoice_number,
        "TxnDate": invoice.issue_date.isoformat(),
        "Line": line_items,
        "TotalAmt": _cents_to_decimal(invoice.total_cents),
        "PrivateNote": f"Invoice {invoice.invoice_id}",
    }
    if invoice.due_date:
        payload["DueDate"] = invoice.due_date.isoformat()
    if invoice.notes:
        payload["CustomerMemo"] = {"value": invoice.notes}
    return payload


def _invoice_payload_hash(payload: dict) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def _get_or_create_sync_state(
    session: AsyncSession,
    org_id: uuid.UUID,
) -> AccountingSyncState:
    existing = await get_sync_state(session, org_id)
    if existing:
        return existing
    sync_state = AccountingSyncState(org_id=org_id, provider=QBO_PROVIDER)
    session.add(sync_state)
    return sync_state


async def record_sync_success(session: AsyncSession, org_id: uuid.UUID) -> None:
    sync_state = await _get_or_create_sync_state(session, org_id)
    sync_state.last_sync_at = datetime.now(timezone.utc)
    sync_state.last_error = None


async def record_sync_error(session: AsyncSession, org_id: uuid.UUID, error: str) -> None:
    sync_state = await _get_or_create_sync_state(session, org_id)
    sync_state.last_sync_at = datetime.now(timezone.utc)
    sync_state.last_error = error


async def _push_invoice(
    client: QboClient,
    session: AsyncSession,
    org_id: uuid.UUID,
    invoice: Invoice,
    existing_map: AccountingInvoiceMap | None,
) -> QboInvoicePushItemResult:
    payload = _build_invoice_payload(invoice)
    payload_hash = _invoice_payload_hash(payload)
    if existing_map and existing_map.last_pushed_hash == payload_hash:
        return QboInvoicePushItemResult(
            invoice_id=invoice.invoice_id,
            remote_invoice_id=existing_map.remote_invoice_id,
            action="skipped",
        )
    if existing_map:
        remote_invoice = await client.get_invoice(existing_map.remote_invoice_id)
        sync_token = remote_invoice.get("SyncToken") or remote_invoice.get("sync_token")
        update_payload = {**payload, "Id": existing_map.remote_invoice_id, "sparse": True}
        if sync_token:
            update_payload["SyncToken"] = sync_token
        response = await client.update_invoice(update_payload)
        existing_map.remote_invoice_id = response.get("Id", existing_map.remote_invoice_id)
        existing_map.last_pushed_hash = payload_hash
        return QboInvoicePushItemResult(
            invoice_id=invoice.invoice_id,
            remote_invoice_id=existing_map.remote_invoice_id,
            action="updated",
        )

    response = await client.create_invoice(payload)
    remote_id = response.get("Id") or response.get("id")
    if not remote_id:
        raise ValueError("missing_remote_invoice_id")
    new_map = AccountingInvoiceMap(
        org_id=org_id,
        local_invoice_id=invoice.invoice_id,
        remote_invoice_id=remote_id,
        last_pushed_hash=payload_hash,
    )
    session.add(new_map)
    return QboInvoicePushItemResult(
        invoice_id=invoice.invoice_id,
        remote_invoice_id=remote_id,
        action="created",
    )


async def push_invoices_to_qbo(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
) -> QboInvoicePushResult:
    if from_date > to_date:
        raise ValueError("invalid_date_range")
    account = await get_account(session, org_id)
    if not account:
        raise ValueError("missing_quickbooks_account")

    invoices = (
        await session.scalars(
            sa.select(Invoice)
            .options(selectinload(Invoice.items))
            .where(
                Invoice.org_id == org_id,
                Invoice.issue_date >= from_date,
                Invoice.issue_date <= to_date,
                Invoice.status.in_(QBO_PUSH_STATUSES),
            )
            .order_by(Invoice.issue_date.asc(), Invoice.invoice_number.asc())
        )
    ).all()
    invoice_ids = [invoice.invoice_id for invoice in invoices]
    existing_maps: dict[str, AccountingInvoiceMap] = {}
    if invoice_ids:
        rows = (
            await session.scalars(
                sa.select(AccountingInvoiceMap).where(
                    AccountingInvoiceMap.org_id == org_id,
                    AccountingInvoiceMap.local_invoice_id.in_(invoice_ids),
                )
            )
        ).all()
        existing_maps = {row.local_invoice_id: row for row in rows}

    created = 0
    updated = 0
    skipped = 0
    access_token, new_refresh = await exchange_refresh_token_for_access_token(account.encrypted_refresh_token)
    if new_refresh and new_refresh != account.encrypted_refresh_token:
        account.encrypted_refresh_token = new_refresh

    client = QBO_CLIENT_FACTORY(access_token, account.realm_id)
    try:
        for invoice in invoices:
            result = await _push_invoice(
                client,
                session,
                org_id,
                invoice,
                existing_maps.get(invoice.invoice_id),
            )
            if result.action == "created":
                created += 1
            elif result.action == "updated":
                updated += 1
            else:
                skipped += 1
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result

    await record_sync_success(session, org_id)
    return QboInvoicePushResult(
        from_date=from_date,
        to_date=to_date,
        created=created,
        updated=updated,
        skipped=skipped,
    )


async def push_invoice_to_qbo(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    invoice_id: str,
) -> QboInvoicePushItemResult:
    account = await get_account(session, org_id)
    if not account:
        raise ValueError("missing_quickbooks_account")
    invoice = await session.scalar(
        sa.select(Invoice).options(selectinload(Invoice.items)).where(
            Invoice.org_id == org_id,
            Invoice.invoice_id == invoice_id,
        )
    )
    if not invoice:
        raise ValueError("missing_invoice")
    if invoice.status not in QBO_PUSH_STATUSES:
        await record_sync_success(session, org_id)
        return QboInvoicePushItemResult(
            invoice_id=invoice.invoice_id,
            remote_invoice_id=None,
            action="skipped",
        )

    existing_map = await session.scalar(
        sa.select(AccountingInvoiceMap).where(
            AccountingInvoiceMap.org_id == org_id,
            AccountingInvoiceMap.local_invoice_id == invoice.invoice_id,
        )
    )
    access_token, new_refresh = await exchange_refresh_token_for_access_token(account.encrypted_refresh_token)
    if new_refresh and new_refresh != account.encrypted_refresh_token:
        account.encrypted_refresh_token = new_refresh
    client = QBO_CLIENT_FACTORY(access_token, account.realm_id)
    try:
        result = await _push_invoice(client, session, org_id, invoice, existing_map)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close_result = close()
            if hasattr(close_result, "__await__"):
                await close_result
    await record_sync_success(session, org_id)
    return result
