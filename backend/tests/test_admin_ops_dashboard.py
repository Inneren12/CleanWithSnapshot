import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain.org_settings import service as org_settings_service
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.domain.bookings.db_models import Booking, Team
from app.domain.invoices import service as invoice_service
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.schemas import InvoiceItemCreate
from app.domain.leads.db_models import Lead


def _lead_payload(name: str = "Ops Lead") -> dict:
    return {
        "name": name,
        "phone": "780-555-1234",
        "email": "lead@example.com",
        "postal_code": "T5A",
        "address": "1 Test St",
        "preferred_dates": ["Mon"],
        "structured_inputs": {"beds": 1, "baths": 1, "cleaning_type": "standard"},
        "estimate_snapshot": {
            "price_cents": 12000,
            "subtotal_cents": 12000,
            "tax_cents": 0,
            "pricing_config_version": "v1",
            "config_hash": "hash",
            "line_items": [],
        },
        "pricing_config_version": "v1",
        "config_hash": "hash",
    }


@pytest.mark.anyio
async def test_ops_dashboard_returns_schema_and_timezone(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Ops Dashboard Org")
        owner = await saas_service.create_user(session, "ops-dashboard@org.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        org_settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        org_settings.timezone = "America/Denver"
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/dashboard/ops",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["org_timezone"] == "America/Denver"
    assert payload["as_of"]
    assert isinstance(payload["critical_alerts"], list)
    assert isinstance(payload["upcoming_events"], list)
    assert isinstance(payload["worker_availability"], list)
    assert "booking_status_today" in payload
    booking_status = payload["booking_status_today"]
    assert set(booking_status.keys()) == {"bands", "totals"}
    assert set(booking_status["totals"].keys()) == {
        "total",
        "pending",
        "confirmed",
        "done",
        "cancelled",
    }


@pytest.mark.anyio
async def test_ops_dashboard_overdue_alert_respects_permissions(async_session_maker, client):
    as_of = date.today()
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Ops Alert Org")
        owner = await saas_service.create_user(session, "ops-owner@org.com", "secret")
        viewer = await saas_service.create_user(session, "ops-viewer@org.com", "secret")
        owner_membership = await saas_service.create_membership(
            session, org, owner, MembershipRole.OWNER
        )
        viewer_membership = await saas_service.create_membership(
            session, org, viewer, MembershipRole.VIEWER
        )

        team = Team(name="Ops Team", org_id=org.org_id)
        session.add(team)
        await session.flush()

        lead = Lead(org_id=org.org_id, **_lead_payload())
        session.add(lead)
        await session.flush()

        booking = Booking(
            booking_id=str(uuid.uuid4()),
            org_id=org.org_id,
            team_id=team.team_id,
            lead_id=lead.lead_id,
            starts_at=datetime.now(tz=timezone.utc),
            duration_minutes=60,
            status="PENDING",
            deposit_cents=0,
            base_charge_cents=0,
            refund_total_cents=0,
            credit_note_total_cents=0,
        )
        session.add(booking)
        await session.flush()

        invoice = await invoice_service.create_invoice_from_order(
            session=session,
            order=booking,
            items=[InvoiceItemCreate(description="Service", qty=1, unit_price_cents=10000)],
            issue_date=as_of - timedelta(days=20),
            due_date=as_of - timedelta(days=8),
            currency="CAD",
        )
        invoice.status = invoice_statuses.INVOICE_STATUS_SENT
        await session.commit()

    owner_token = saas_service.build_access_token(owner, owner_membership)
    owner_response = client.get(
        "/v1/admin/dashboard/ops",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owner_response.status_code == 200
    owner_alerts = owner_response.json()["critical_alerts"]
    assert any(alert["type"] == "overdue_invoices" for alert in owner_alerts)

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    viewer_response = client.get(
        "/v1/admin/dashboard/ops",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert viewer_response.status_code == 200
    viewer_alerts = viewer_response.json()["critical_alerts"]
    assert not any(alert["type"] == "overdue_invoices" for alert in viewer_alerts)


@pytest.mark.anyio
async def test_ops_dashboard_overdue_alert_ignores_draft_invoices(async_session_maker, client):
    as_of = date.today()
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Ops Draft Org")
        owner = await saas_service.create_user(session, "ops-draft@org.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)

        team = Team(name="Draft Team", org_id=org.org_id)
        session.add(team)
        await session.flush()

        lead = Lead(org_id=org.org_id, **_lead_payload())
        session.add(lead)
        await session.flush()

        booking = Booking(
            booking_id=str(uuid.uuid4()),
            org_id=org.org_id,
            team_id=team.team_id,
            lead_id=lead.lead_id,
            starts_at=datetime.now(tz=timezone.utc),
            duration_minutes=60,
            status="PENDING",
            deposit_cents=0,
            base_charge_cents=0,
            refund_total_cents=0,
            credit_note_total_cents=0,
        )
        session.add(booking)
        await session.flush()

        invoice = await invoice_service.create_invoice_from_order(
            session=session,
            order=booking,
            items=[InvoiceItemCreate(description="Service", qty=1, unit_price_cents=10000)],
            issue_date=as_of - timedelta(days=20),
            due_date=as_of - timedelta(days=8),
            currency="CAD",
        )
        invoice.status = invoice_statuses.INVOICE_STATUS_DRAFT
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/dashboard/ops",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    alerts = response.json()["critical_alerts"]
    assert not any(alert["type"] == "overdue_invoices" for alert in alerts)
