import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.domain.feature_modules import service as feature_service
from app.domain.org_settings import service as org_settings_service
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.domain.bookings.db_models import Booking, Team
from app.domain.clients.db_models import ClientFeedback, ClientUser
from app.domain.notifications_center.db_models import NotificationEvent, NotificationRead
from app.domain.leads.db_models import Lead
from app.domain.quality.db_models import QualityIssue


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
async def test_ops_dashboard_upcoming_unassigned_booking(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Ops Upcoming Org")
        owner = await saas_service.create_user(session, "ops-upcoming@org.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)

        team = Team(name="Upcoming Team", org_id=org.org_id)
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
            starts_at=datetime.now(tz=timezone.utc) + timedelta(hours=2),
            duration_minutes=90,
            status="PENDING",
            deposit_cents=0,
            base_charge_cents=0,
            refund_total_cents=0,
            credit_note_total_cents=0,
        )
        session.add(booking)
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/dashboard/ops",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    events = response.json()["upcoming_events"]
    assert any(
        event["entity_ref"]
        and event["entity_ref"].get("booking_id") == booking.booking_id
        and "Unassigned booking" in event["title"]
        for event in events
    )


@pytest.mark.anyio
async def test_ops_dashboard_critical_alerts_reflect_notifications(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Ops Alert Org")
        owner = await saas_service.create_user(session, "ops-owner@org.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org.org_id,
            {"module.notifications_center": True},
        )

        alert_event = NotificationEvent(
            org_id=org.org_id,
            priority="CRITICAL",
            type="dispatch_risk",
            title="Dispatch risk",
            body="Dispatch coverage is below threshold.",
            action_href="/admin/dispatcher",
            action_kind="open_booking",
        )
        secondary_event = NotificationEvent(
            org_id=org.org_id,
            priority="HIGH",
            type="billing_attention",
            title="Billing attention",
            body="High value invoice needs review.",
        )
        low_event = NotificationEvent(
            org_id=org.org_id,
            priority="LOW",
            type="info_only",
            title="Info",
            body="FYI alert.",
        )
        session.add_all([alert_event, secondary_event, low_event])
        await session.flush()

        read_record = NotificationRead(
            org_id=org.org_id,
            user_id=f"saas:{owner.user_id}",
            event_id=secondary_event.id,
        )
        session.add(read_record)
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/dashboard/ops",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    alerts = response.json()["critical_alerts"]
    assert any(alert["notification_id"] == str(alert_event.id) for alert in alerts)
    assert all(alert["notification_id"] != str(secondary_event.id) for alert in alerts)
    assert all(alert["notification_id"] != str(low_event.id) for alert in alerts)


@pytest.mark.anyio
async def test_ops_dashboard_critical_alerts_respect_notifications_module(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Ops Notifications Module Org")
        owner = await saas_service.create_user(session, "ops-module@org.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org.org_id,
            {"module.notifications_center": False},
        )
        session.add(
            NotificationEvent(
                org_id=org.org_id,
                priority="CRITICAL",
                type="dispatch_risk",
                title="Dispatch risk",
                body="Dispatch coverage is below threshold.",
            )
        )
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/dashboard/ops",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    alerts = response.json()["critical_alerts"]
    assert alerts == []


@pytest.mark.anyio
async def test_ops_dashboard_quality_today_respects_org_timezone_and_alerts(
    async_session_maker, client
):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Ops Quality Org")
        owner = await saas_service.create_user(session, "ops-quality@org.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)

        org_settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        org_settings.timezone = "America/Los_Angeles"

        team = Team(name="Quality Team", org_id=org.org_id)
        session.add(team)
        await session.flush()

        client_user = ClientUser(
            org_id=org.org_id,
            name="Quality Client",
            email="quality-client@example.com",
            phone="+1 555-000-2222",
            address="12 Quality Way",
            is_active=True,
        )
        session.add(client_user)
        await session.flush()

        booking_before = Booking(
            booking_id=str(uuid.uuid4()),
            org_id=org.org_id,
            client_id=client_user.client_id,
            team_id=team.team_id,
            starts_at=datetime.now(tz=timezone.utc),
            duration_minutes=60,
            status="COMPLETED",
            deposit_cents=0,
            base_charge_cents=0,
            refund_total_cents=0,
            credit_note_total_cents=0,
        )
        booking_today = Booking(
            booking_id=str(uuid.uuid4()),
            org_id=org.org_id,
            client_id=client_user.client_id,
            team_id=team.team_id,
            starts_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
            duration_minutes=60,
            status="COMPLETED",
            deposit_cents=0,
            base_charge_cents=0,
            refund_total_cents=0,
            credit_note_total_cents=0,
        )
        session.add_all([booking_before, booking_today])
        await session.flush()

        org_tz = ZoneInfo("America/Los_Angeles")
        now_local = datetime.now(org_tz)
        today_start_local = datetime.combine(now_local.date(), time.min, tzinfo=org_tz)
        before_today_local = today_start_local - timedelta(minutes=5)
        today_local = today_start_local + timedelta(hours=1)

        feedback_before = ClientFeedback(
            org_id=org.org_id,
            client_id=client_user.client_id,
            booking_id=booking_before.booking_id,
            rating=5,
            comment="Yesterday review",
            channel="admin",
            created_at=before_today_local.astimezone(timezone.utc),
        )
        feedback_today = ClientFeedback(
            org_id=org.org_id,
            client_id=client_user.client_id,
            booking_id=booking_today.booking_id,
            rating=1,
            comment="Negative review today",
            channel="admin",
            created_at=today_local.astimezone(timezone.utc),
        )
        session.add_all([feedback_before, feedback_today])

        issue = QualityIssue(
            org_id=org.org_id,
            client_id=client_user.client_id,
            rating=1,
            status="open",
        )
        session.add(issue)
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/dashboard/ops",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    quality_today = payload["quality_today"]
    assert quality_today["reviews_count"] == 1
    assert quality_today["avg_rating"] == 1.0
    assert quality_today["open_critical_issues"] == 1


@pytest.mark.anyio
async def test_ops_dashboard_quality_today_requires_permission(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Ops Quality Permissions Org")
        owner = await saas_service.create_user(session, "ops-quality-owner@org.com", "secret")
        viewer = await saas_service.create_user(session, "ops-quality-viewer@org.com", "secret")
        owner_membership = await saas_service.create_membership(
            session, org, owner, MembershipRole.OWNER
        )
        viewer_membership = await saas_service.create_membership(
            session, org, viewer, MembershipRole.VIEWER
        )

        team = Team(name="Quality Permissions Team", org_id=org.org_id)
        session.add(team)
        await session.flush()

        client_user = ClientUser(
            org_id=org.org_id,
            name="Quality Viewer Client",
            email="quality-viewer@example.com",
            phone="+1 555-000-3333",
            address="34 Quality Way",
            is_active=True,
        )
        session.add(client_user)
        await session.flush()

        booking = Booking(
            booking_id=str(uuid.uuid4()),
            org_id=org.org_id,
            client_id=client_user.client_id,
            team_id=team.team_id,
            starts_at=datetime.now(tz=timezone.utc),
            duration_minutes=60,
            status="COMPLETED",
            deposit_cents=0,
            base_charge_cents=0,
            refund_total_cents=0,
            credit_note_total_cents=0,
        )
        session.add(booking)
        await session.flush()

        feedback = ClientFeedback(
            org_id=org.org_id,
            client_id=client_user.client_id,
            booking_id=booking.booking_id,
            rating=2,
            comment="Viewer review",
            channel="admin",
        )
        issue = QualityIssue(
            org_id=org.org_id,
            client_id=client_user.client_id,
            rating=1,
            status="open",
        )
        session.add_all([feedback, issue])
        await session.commit()

    owner_token = saas_service.build_access_token(owner, owner_membership)
    owner_response = client.get(
        "/v1/admin/dashboard/ops",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owner_response.status_code == 200
    assert "quality_today" in owner_response.json()

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    viewer_response = client.get(
        "/v1/admin/dashboard/ops",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert viewer_response.status_code == 200
    viewer_payload = viewer_response.json()
    assert "quality_today" not in viewer_payload
