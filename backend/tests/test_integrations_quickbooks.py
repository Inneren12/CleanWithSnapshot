from datetime import date

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.domain.config_audit import service as config_audit_service
from app.domain.feature_modules import service as feature_service
from app.domain.integrations import qbo_service
from app.domain.integrations.db_models import AccountingInvoiceMap, IntegrationsAccountingAccount
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice, InvoiceItem, Payment
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.settings import settings


async def _enable_quickbooks(session, org_id):
    await feature_service.upsert_org_feature_overrides(
        session,
        org_id,
        {"module.integrations": True, "integrations.accounting.quickbooks": True},
        audit_actor=config_audit_service.system_actor("tests"),
        request_id=None,
    )


async def _create_invoice(session, *, org_id, invoice_number: str, status: str) -> Invoice:
    today = date.today()
    invoice = Invoice(
        org_id=org_id,
        invoice_number=invoice_number,
        status=status,
        issue_date=today,
        due_date=today,
        currency="CAD",
        subtotal_cents=10000,
        taxable_subtotal_cents=0,
        tax_cents=0,
        total_cents=10000,
    )
    session.add(invoice)
    await session.flush()
    item = InvoiceItem(
        invoice_id=invoice.invoice_id,
        description="Service",
        qty=1,
        unit_price_cents=10000,
        line_total_cents=10000,
        tax_rate=None,
    )
    session.add(item)
    await session.flush()
    return invoice


@pytest.mark.anyio
async def test_qbo_status_reflects_db(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Status Org")
        owner = await saas_service.create_user(session, "owner@qbo.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_quickbooks(session, org.org_id)
        session.add(
            IntegrationsAccountingAccount(
                org_id=org.org_id,
                provider=qbo_service.QBO_PROVIDER,
                encrypted_refresh_token="refresh-token",
                realm_id="realm-1",
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/integrations/accounting/quickbooks/status",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is True
    assert payload["realm_id"] == "realm-1"


@pytest.mark.anyio
async def test_owner_can_connect_and_disconnect_quickbooks(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Connect Org")
        owner = await saas_service.create_user(session, "owner@qbo-connect.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_quickbooks(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"refresh_token": "refresh-123"})

    monkeypatch.setattr(qbo_service, "TOKEN_EXCHANGE_TRANSPORT", httpx.MockTransport(handler))

    owner_token = saas_service.build_access_token(owner, membership)
    callback = client.post(
        "/v1/admin/integrations/accounting/quickbooks/connect/callback",
        json={"code": "auth-code", "realm_id": "realm-123", "state": str(org.org_id)},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert callback.status_code == 200
    assert callback.json()["connected"] is True

    status_resp = client.get(
        "/v1/admin/integrations/accounting/quickbooks/status",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["connected"] is True

    disconnect = client.post(
        "/v1/admin/integrations/accounting/quickbooks/disconnect",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert disconnect.status_code == 200
    assert disconnect.json()["connected"] is False


@pytest.mark.anyio
async def test_viewer_cannot_connect_or_disconnect_quickbooks(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Viewer Org")
        owner = await saas_service.create_user(session, "owner@qbo-viewer.com", "secret")
        await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        viewer = await saas_service.create_user(session, "viewer@qbo-viewer.com", "secret")
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await _enable_quickbooks(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    start_resp = client.post(
        "/v1/admin/integrations/accounting/quickbooks/connect/start",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert start_resp.status_code == 403

    disconnect_resp = client.post(
        "/v1/admin/integrations/accounting/quickbooks/disconnect",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert disconnect_resp.status_code == 403


@pytest.mark.anyio
async def test_viewer_can_read_quickbooks_status(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Viewer Status Org")
        owner = await saas_service.create_user(session, "owner@qbo-viewer-status.com", "secret")
        await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        viewer = await saas_service.create_user(session, "viewer@qbo-viewer-status.com", "secret")
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await _enable_quickbooks(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    response = client.get(
        "/v1/admin/integrations/accounting/quickbooks/status",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    assert response.json()["connected"] is False


@pytest.mark.anyio
async def test_qbo_push_creates_remote_invoice_once(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Push Org")
        owner = await saas_service.create_user(session, "owner@qbo-push.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_quickbooks(session, org.org_id)
        session.add(
            IntegrationsAccountingAccount(
                org_id=org.org_id,
                provider=qbo_service.QBO_PROVIDER,
                encrypted_refresh_token="refresh-token",
                realm_id="realm-1",
            )
        )
        invoice = await _create_invoice(
            session,
            org_id=org.org_id,
            invoice_number="INV-QBO-1",
            status=invoice_statuses.INVOICE_STATUS_SENT,
        )
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    async def exchange_refresh(_refresh: str) -> tuple[str, str | None]:
        return "access-token", None

    class StubQboClient:
        def __init__(self):
            self.create_calls = 0
            self.get_calls = 0
            self.update_calls = 0

        async def close(self) -> None:
            return None

        async def create_invoice(self, payload: dict) -> dict:
            self.create_calls += 1
            return {"Id": "remote-1"}

        async def get_invoice(self, invoice_id: str) -> dict:
            self.get_calls += 1
            return {"Id": invoice_id, "SyncToken": "1"}

        async def update_invoice(self, payload: dict) -> dict:
            self.update_calls += 1
            return {"Id": payload.get("Id", "remote-1")}

    stub_client = StubQboClient()

    monkeypatch.setattr(qbo_service, "exchange_refresh_token_for_access_token", exchange_refresh)
    monkeypatch.setattr(qbo_service, "QBO_CLIENT_FACTORY", lambda *_args, **_kwargs: stub_client)

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.post(
        "/v1/admin/integrations/accounting/quickbooks/push",
        params={"from": date.today().isoformat(), "to": date.today().isoformat()},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] == 1
    assert payload["updated"] == 0
    assert payload["skipped"] == 0
    assert stub_client.create_calls == 1

    async with async_session_maker() as session:
        mapping = await session.scalar(
            sa.select(AccountingInvoiceMap).where(
                AccountingInvoiceMap.org_id == org.org_id,
                AccountingInvoiceMap.local_invoice_id == invoice.invoice_id,
            )
        )
        assert mapping is not None
        assert mapping.remote_invoice_id == "remote-1"


@pytest.mark.anyio
async def test_qbo_repush_unchanged_invoice_is_noop(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Repush Org")
        owner = await saas_service.create_user(session, "owner@qbo-repush.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_quickbooks(session, org.org_id)
        session.add(
            IntegrationsAccountingAccount(
                org_id=org.org_id,
                provider=qbo_service.QBO_PROVIDER,
                encrypted_refresh_token="refresh-token",
                realm_id="realm-1",
            )
        )
        await _create_invoice(
            session,
            org_id=org.org_id,
            invoice_number="INV-QBO-2",
            status=invoice_statuses.INVOICE_STATUS_SENT,
        )
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    async def exchange_refresh(_refresh: str) -> tuple[str, str | None]:
        return "access-token", None

    class StubQboClient:
        def __init__(self):
            self.create_calls = 0

        async def close(self) -> None:
            return None

        async def create_invoice(self, payload: dict) -> dict:
            self.create_calls += 1
            return {"Id": "remote-2"}

        async def get_invoice(self, invoice_id: str) -> dict:
            return {"Id": invoice_id, "SyncToken": "1"}

        async def update_invoice(self, payload: dict) -> dict:
            return {"Id": payload.get("Id", "remote-2")}

    stub_client = StubQboClient()

    monkeypatch.setattr(qbo_service, "exchange_refresh_token_for_access_token", exchange_refresh)
    monkeypatch.setattr(qbo_service, "QBO_CLIENT_FACTORY", lambda *_args, **_kwargs: stub_client)

    owner_token = saas_service.build_access_token(owner, membership)
    first = client.post(
        "/v1/admin/integrations/accounting/quickbooks/push",
        params={"from": date.today().isoformat(), "to": date.today().isoformat()},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert first.status_code == 200
    second = client.post(
        "/v1/admin/integrations/accounting/quickbooks/push",
        params={"from": date.today().isoformat(), "to": date.today().isoformat()},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["skipped"] == 1
    assert stub_client.create_calls == 1


@pytest.mark.anyio
async def test_qbo_update_invoice_total_triggers_update(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Update Org")
        owner = await saas_service.create_user(session, "owner@qbo-update.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_quickbooks(session, org.org_id)
        session.add(
            IntegrationsAccountingAccount(
                org_id=org.org_id,
                provider=qbo_service.QBO_PROVIDER,
                encrypted_refresh_token="refresh-token",
                realm_id="realm-1",
            )
        )
        invoice = await _create_invoice(
            session,
            org_id=org.org_id,
            invoice_number="INV-QBO-3",
            status=invoice_statuses.INVOICE_STATUS_SENT,
        )
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    async def exchange_refresh(_refresh: str) -> tuple[str, str | None]:
        return "access-token", None

    class StubQboClient:
        def __init__(self):
            self.create_calls = 0
            self.update_calls = 0

        async def close(self) -> None:
            return None

        async def create_invoice(self, payload: dict) -> dict:
            self.create_calls += 1
            return {"Id": "remote-3"}

        async def get_invoice(self, invoice_id: str) -> dict:
            return {"Id": invoice_id, "SyncToken": "1"}

        async def update_invoice(self, payload: dict) -> dict:
            self.update_calls += 1
            return {"Id": payload.get("Id", "remote-3")}

    stub_client = StubQboClient()

    monkeypatch.setattr(qbo_service, "exchange_refresh_token_for_access_token", exchange_refresh)
    monkeypatch.setattr(qbo_service, "QBO_CLIENT_FACTORY", lambda *_args, **_kwargs: stub_client)

    owner_token = saas_service.build_access_token(owner, membership)
    first = client.post(
        "/v1/admin/integrations/accounting/quickbooks/push",
        params={"from": date.today().isoformat(), "to": date.today().isoformat()},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert first.status_code == 200

    async with async_session_maker() as session:
        refreshed = await session.scalar(
            sa.select(Invoice)
            .options(selectinload(Invoice.items))
            .where(Invoice.invoice_id == invoice.invoice_id)
        )
        refreshed.total_cents = 12000
        refreshed.subtotal_cents = 12000
        refreshed.items[0].unit_price_cents = 12000
        refreshed.items[0].line_total_cents = 12000
        await session.commit()

    second = client.post(
        "/v1/admin/integrations/accounting/quickbooks/push",
        params={"from": date.today().isoformat(), "to": date.today().isoformat()},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["updated"] == 1
    assert stub_client.update_calls == 1


@pytest.mark.anyio
async def test_qbo_pull_status_updates_paid_once(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Pull Org")
        owner = await saas_service.create_user(session, "owner@qbo-pull.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_quickbooks(session, org.org_id)
        session.add(
            IntegrationsAccountingAccount(
                org_id=org.org_id,
                provider=qbo_service.QBO_PROVIDER,
                encrypted_refresh_token="refresh-token",
                realm_id="realm-1",
            )
        )
        invoice = await _create_invoice(
            session,
            org_id=org.org_id,
            invoice_number="INV-QBO-4",
            status=invoice_statuses.INVOICE_STATUS_SENT,
        )
        session.add(
            AccountingInvoiceMap(
                org_id=org.org_id,
                local_invoice_id=invoice.invoice_id,
                remote_invoice_id="remote-4",
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    async def exchange_refresh(_refresh: str) -> tuple[str, str | None]:
        return "access-token", None

    class StubQboClient:
        def __init__(self):
            self.query_calls = 0

        async def close(self) -> None:
            return None

        async def query_payments(self, *, from_date, to_date) -> list[dict]:
            self.query_calls += 1
            return [
                {
                    "Id": "payment-1",
                    "TxnDate": date.today().isoformat(),
                    "TotalAmt": "100.00",
                    "Line": [
                        {
                            "Amount": "100.00",
                            "LinkedTxn": [{"TxnId": "remote-4", "TxnType": "Invoice"}],
                        }
                    ],
                }
            ]

    stub_client = StubQboClient()
    monkeypatch.setattr(qbo_service, "exchange_refresh_token_for_access_token", exchange_refresh)
    monkeypatch.setattr(qbo_service, "QBO_CLIENT_FACTORY", lambda *_args, **_kwargs: stub_client)

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.post(
        "/v1/admin/integrations/accounting/quickbooks/pull_status",
        params={"from": date.today().isoformat(), "to": date.today().isoformat()},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200

    async with async_session_maker() as session:
        refreshed = await session.scalar(
            sa.select(Invoice).where(Invoice.invoice_id == invoice.invoice_id)
        )
        assert refreshed.status == invoice_statuses.INVOICE_STATUS_PAID
        payments = (
            await session.scalars(
                sa.select(Payment).where(
                    Payment.provider == qbo_service.QBO_PROVIDER,
                    Payment.provider_ref == "payment-1",
                )
            )
        ).all()
        assert len(payments) == 1

    second = client.post(
        "/v1/admin/integrations/accounting/quickbooks/pull_status",
        params={"from": date.today().isoformat(), "to": date.today().isoformat()},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert second.status_code == 200

    async with async_session_maker() as session:
        payments = (
            await session.scalars(
                sa.select(Payment).where(
                    Payment.provider == qbo_service.QBO_PROVIDER,
                    Payment.provider_ref == "payment-1",
                )
            )
        ).all()
        assert len(payments) == 1
