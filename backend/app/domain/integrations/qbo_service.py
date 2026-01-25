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

from app.domain.config_audit import ConfigAuditActor
from app.domain.integrations.db_models import AccountingInvoiceMap, AccountingSyncState, IntegrationsAccountingAccount
from app.domain.integration_audit import IntegrationAuditContext, IntegrationScope
from app.domain.integration_audit import service as integration_audit_service
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices import service as invoice_service
from app.domain.invoices.db_models import Invoice, Payment
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


@dataclass(frozen=True)
class QboInvoicePullResult:
    from_date: date
    to_date: date
    payments_recorded: int
    payments_skipped: int
    invoices_touched: int

    @property
    def total(self) -> int:
        return self.payments_recorded + self.payments_skipped


@dataclass(frozen=True)
class QboPaymentLine:
    payment_id: str
    remote_invoice_id: str
    amount_cents: int
    currency: str | None
    received_at: datetime | None


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
    *,
    audit_actor: ConfigAuditActor,
    request_id: str | None,
) -> IntegrationsAccountingAccount:
    account = await get_account(session, org_id)
    before_snapshot = await _snapshot_quickbooks_integration(session, org_id)
    if account:
        account.encrypted_refresh_token = refresh_token
        account.realm_id = realm_id
        await session.flush()
        after_snapshot = await _snapshot_quickbooks_integration(session, org_id)
        await integration_audit_service.audit_integration_config_change(
            session,
            actor=audit_actor,
            org_id=org_id,
            context=IntegrationAuditContext(
                integration_type="quickbooks",
                integration_scope=IntegrationScope.ORG,
            ),
            before_state=before_snapshot,
            after_state=after_snapshot,
            request_id=request_id,
        )
        return account
    account = IntegrationsAccountingAccount(
        org_id=org_id,
        provider=QBO_PROVIDER,
        encrypted_refresh_token=refresh_token,
        realm_id=realm_id,
    )
    session.add(account)
    await session.flush()
    after_snapshot = await _snapshot_quickbooks_integration(session, org_id)
    await integration_audit_service.audit_integration_config_change(
        session,
        actor=audit_actor,
        org_id=org_id,
        context=IntegrationAuditContext(
            integration_type="quickbooks",
            integration_scope=IntegrationScope.ORG,
        ),
        before_state=before_snapshot,
        after_state=after_snapshot,
        request_id=request_id,
    )
    return account


async def get_sync_state(
    session: AsyncSession, org_id: uuid.UUID
) -> AccountingSyncState | None:
    return await session.get(
        AccountingSyncState,
        {"org_id": org_id, "provider": QBO_PROVIDER},
    )


async def disconnect_quickbooks(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    audit_actor: ConfigAuditActor,
    request_id: str | None,
) -> None:
    before_snapshot = await _snapshot_quickbooks_integration(session, org_id)
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
    await session.flush()
    await integration_audit_service.audit_integration_config_change(
        session,
        actor=audit_actor,
        org_id=org_id,
        context=IntegrationAuditContext(
            integration_type="quickbooks",
            integration_scope=IntegrationScope.ORG,
        ),
        before_state=before_snapshot,
        after_state=None,
        request_id=request_id,
    )


async def _snapshot_quickbooks_integration(session: AsyncSession, org_id: uuid.UUID) -> dict[str, object | None]:
    account = await get_account(session, org_id)
    sync_state = await get_sync_state(session, org_id)
    return {
        "connected": bool(account),
        "realm_id": account.realm_id if account else None,
        "encrypted_refresh_token": account.encrypted_refresh_token if account else None,
        "last_sync_at": sync_state.last_sync_at.isoformat() if sync_state and sync_state.last_sync_at else None,
        "last_error": sync_state.last_error if sync_state else None,
    }


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

    async def query_payments(self, *, from_date: date, to_date: date) -> list[dict]:
        query = (
            "select * from Payment "
            f"where TxnDate >= '{from_date.isoformat()}' "
            f"and TxnDate <= '{to_date.isoformat()}'"
        )
        response = await self._client.get(f"/{self._realm_id}/query", params={"query": query})
        if response.status_code >= 400:
            raise ValueError("qbo_payment_query_failed")
        data = response.json()
        query_response = data.get("QueryResponse", {})
        payments = query_response.get("Payment", [])
        if isinstance(payments, list):
            return payments
        if payments:
            return [payments]
        return []


QBO_CLIENT_FACTORY: Callable[[str, str], QboClient] = (
    lambda access_token, realm_id: QboClient(access_token, realm_id, transport=QBO_API_TRANSPORT)
)


def _cents_to_decimal(cents: int) -> str:
    value = (Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"))
    return f"{value:.2f}"


def _decimal_to_cents(amount: str | int | float | Decimal | None) -> int:
    if amount is None:
        return 0
    value = Decimal(str(amount))
    return int((value * Decimal("100")).quantize(Decimal("1")))


def _parse_qbo_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return datetime.combine(parsed, datetime.min.time(), tzinfo=timezone.utc)


def _extract_payment_lines(payments: list[dict]) -> list[QboPaymentLine]:
    aggregated: dict[tuple[str, str], QboPaymentLine] = {}
    for payment in payments:
        payment_id = payment.get("Id") or payment.get("id")
        if not payment_id:
            continue
        received_at = _parse_qbo_date(payment.get("TxnDate") or payment.get("txn_date"))
        currency = None
        currency_ref = payment.get("CurrencyRef")
        if isinstance(currency_ref, dict):
            currency = currency_ref.get("value") or currency_ref.get("name")
        total_amount_cents = _decimal_to_cents(payment.get("TotalAmt") or payment.get("total_amount"))
        lines = payment.get("Line") or []
        if not isinstance(lines, list):
            lines = [lines]
        linked_txns: list[dict] = payment.get("LinkedTxn") or []
        if linked_txns and not lines:
            lines = [{"LinkedTxn": linked_txns, "Amount": payment.get("TotalAmt")}]
        for line in lines:
            line_amount_cents = _decimal_to_cents(line.get("Amount")) or total_amount_cents
            for linked in line.get("LinkedTxn", []) or []:
                if linked.get("TxnType") != "Invoice":
                    continue
                remote_invoice_id = linked.get("TxnId") or linked.get("txn_id")
                if not remote_invoice_id:
                    continue
                key = (payment_id, remote_invoice_id)
                existing = aggregated.get(key)
                if existing:
                    aggregated[key] = QboPaymentLine(
                        payment_id=payment_id,
                        remote_invoice_id=remote_invoice_id,
                        amount_cents=existing.amount_cents + line_amount_cents,
                        currency=currency or existing.currency,
                        received_at=received_at or existing.received_at,
                    )
                else:
                    aggregated[key] = QboPaymentLine(
                        payment_id=payment_id,
                        remote_invoice_id=remote_invoice_id,
                        amount_cents=line_amount_cents,
                        currency=currency,
                        received_at=received_at,
                    )
    return list(aggregated.values())


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


async def pull_invoice_status_from_qbo(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
) -> QboInvoicePullResult:
    if from_date > to_date:
        raise ValueError("invalid_date_range")
    account = await get_account(session, org_id)
    if not account:
        raise ValueError("missing_quickbooks_account")

    invoice_rows = (
        await session.execute(
            sa.select(Invoice, AccountingInvoiceMap)
            .join(AccountingInvoiceMap, AccountingInvoiceMap.local_invoice_id == Invoice.invoice_id)
            .where(
                Invoice.org_id == org_id,
                Invoice.issue_date >= from_date,
                Invoice.issue_date <= to_date,
            )
        )
    ).all()
    if not invoice_rows:
        await record_sync_success(session, org_id)
        return QboInvoicePullResult(
            from_date=from_date,
            to_date=to_date,
            payments_recorded=0,
            payments_skipped=0,
            invoices_touched=0,
        )

    access_token, new_refresh = await exchange_refresh_token_for_access_token(account.encrypted_refresh_token)
    if new_refresh and new_refresh != account.encrypted_refresh_token:
        account.encrypted_refresh_token = new_refresh
    client = QBO_CLIENT_FACTORY(access_token, account.realm_id)
    payments_recorded = 0
    payments_skipped = 0
    invoices_touched = 0
    try:
        payments = await client.query_payments(from_date=from_date, to_date=to_date)
        payment_lines = _extract_payment_lines(payments)
        lines_by_invoice: dict[str, list[QboPaymentLine]] = {}
        for line in payment_lines:
            lines_by_invoice.setdefault(line.remote_invoice_id, []).append(line)

        for invoice, mapping in invoice_rows:
            lines = lines_by_invoice.get(mapping.remote_invoice_id, [])
            if not lines:
                continue
            invoices_touched += 1
            for line in lines:
                existing_payment = await session.scalar(
                    sa.select(Payment.payment_id).where(
                        Payment.provider == QBO_PROVIDER,
                        Payment.provider_ref == line.payment_id,
                    )
                )
                if existing_payment:
                    await invoice_service.refresh_invoice_payment_status(session, invoice)
                    payments_skipped += 1
                    continue
                await invoice_service.register_payment(
                    session,
                    invoice,
                    provider=QBO_PROVIDER,
                    method=invoice_statuses.PAYMENT_METHOD_OTHER,
                    amount_cents=line.amount_cents,
                    currency=line.currency or invoice.currency,
                    status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                    received_at=line.received_at,
                    reference="QuickBooks Online",
                    provider_ref=line.payment_id,
                )
                payments_recorded += 1
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close_result = close()
            if hasattr(close_result, "__await__"):
                await close_result

    await record_sync_success(session, org_id)
    return QboInvoicePullResult(
        from_date=from_date,
        to_date=to_date,
        payments_recorded=payments_recorded,
        payments_skipped=payments_skipped,
        invoices_touched=invoices_touched,
    )
