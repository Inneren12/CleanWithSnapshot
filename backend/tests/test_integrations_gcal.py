from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking, Team
from app.domain.feature_modules import service as feature_service
from app.domain.integrations import gcal_service
from app.domain.integrations.db_models import (
    GcalSyncMode,
    IntegrationsGcalCalendar,
    IntegrationsGcalEventMap,
    IntegrationsGoogleAccount,
    ScheduleExternalBlock,
)
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.settings import settings


async def _enable_gcal(session: AsyncSession, org_id):
    await feature_service.upsert_org_feature_overrides(
        session,
        org_id,
        {"module.integrations": True, "integrations.google_calendar": True},
    )


def _transport_for_events(events: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        if request.url.host == "www.googleapis.com" and "calendar/v3/calendars" in str(request.url):
            return httpx.Response(200, json={"items": events})
        return httpx.Response(404, json={"error": "unknown"})

    return httpx.MockTransport(handler)


async def _create_team(session: AsyncSession, org_id, name_suffix: str) -> Team:
    team = Team(org_id=org_id, name=f"Gcal Team {name_suffix}")
    session.add(team)
    await session.flush()
    return team


async def _create_booking(session: AsyncSession, org_id, team_id: int, starts_at: datetime) -> Booking:
    booking = Booking(
        org_id=org_id,
        team_id=team_id,
        starts_at=starts_at,
        duration_minutes=90,
        status="CONFIRMED",
    )
    session.add(booking)
    await session.flush()
    return booking


def _export_url(start: datetime, end: datetime) -> str:
    query = urlencode({"from": start.isoformat(), "to": end.isoformat()})
    return f"/v1/admin/integrations/google/gcal/export_sync?{query}"


def _mock_gcal_client(monkeypatch, created, updated, event_id: str = "event-1") -> None:
    class FakeGcalClient:
        def __init__(self):
            self.event_id = event_id

        async def create_event(self, calendar_id: str, payload: dict) -> dict:
            created.append({"calendar_id": calendar_id, "payload": payload})
            return {"id": self.event_id}

        async def update_event(self, calendar_id: str, event_id: str, payload: dict) -> dict:
            updated.append({"calendar_id": calendar_id, "event_id": event_id, "payload": payload})
            return {"id": event_id}

        async def close(self) -> None:
            return None

    def factory(_access_token: str) -> FakeGcalClient:
        return FakeGcalClient()

    monkeypatch.setattr(gcal_service, "GCAL_CLIENT_FACTORY", factory)


def _mock_access_token(monkeypatch) -> None:
    async def _exchange_refresh_token(_refresh_token: str) -> str:
        return "access-token"

    monkeypatch.setattr(gcal_service, "exchange_refresh_token_for_access_token", _exchange_refresh_token)


@pytest.mark.anyio
async def test_gcal_status_reflects_db(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Status Org")
        owner = await saas_service.create_user(session, "owner@gcal.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_gcal(session, org.org_id)
        session.add(
            IntegrationsGoogleAccount(
                org_id=org.org_id,
                encrypted_refresh_token="refresh-token",
                token_scopes=["scope1"],
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/integrations/google/status",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is True


@pytest.mark.anyio
async def test_owner_can_connect_and_disconnect_google_calendar(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Connect Org")
        owner = await saas_service.create_user(session, "owner@gcal-connect.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_gcal(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"refresh_token": "refresh-123", "scope": "scope1 scope2"})

    monkeypatch.setattr(gcal_service, "TOKEN_EXCHANGE_TRANSPORT", httpx.MockTransport(handler))

    owner_token = saas_service.build_access_token(owner, membership)
    callback = client.post(
        "/v1/admin/integrations/google/connect/callback",
        json={"code": "auth-code", "state": str(org.org_id)},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert callback.status_code == 200
    assert callback.json()["connected"] is True

    status_resp = client.get(
        "/v1/admin/integrations/google/status",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["connected"] is True

    disconnect = client.post(
        "/v1/admin/integrations/google/disconnect",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert disconnect.status_code == 200
    assert disconnect.json()["connected"] is False


@pytest.mark.anyio
async def test_viewer_cannot_connect_or_disconnect_google_calendar(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Viewer Org")
        owner = await saas_service.create_user(session, "owner@gcal-viewer.com", "secret")
        await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        viewer = await saas_service.create_user(session, "viewer@gcal-viewer.com", "secret")
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await _enable_gcal(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    start_resp = client.post(
        "/v1/admin/integrations/google/connect/start",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert start_resp.status_code == 403

    disconnect_resp = client.post(
        "/v1/admin/integrations/google/disconnect",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert disconnect_resp.status_code == 403


@pytest.mark.anyio
async def test_viewer_can_read_google_calendar_status(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Viewer Status Org")
        owner = await saas_service.create_user(session, "owner@gcal-viewer-status.com", "secret")
        await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        viewer = await saas_service.create_user(session, "viewer@gcal-viewer-status.com", "secret")
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await _enable_gcal(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    response = client.get(
        "/v1/admin/integrations/google/status",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    assert response.json()["connected"] is False


@pytest.mark.anyio
async def test_google_calendar_oauth_tokens_not_logged(async_session_maker, client, monkeypatch, caplog):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Log Org")
        owner = await saas_service.create_user(session, "owner@gcal-log.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_gcal(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"refresh_token": "refresh-logged", "scope": "scope1"})

    monkeypatch.setattr(gcal_service, "TOKEN_EXCHANGE_TRANSPORT", httpx.MockTransport(handler))

    owner_token = saas_service.build_access_token(owner, membership)
    with caplog.at_level("INFO"):
        response = client.post(
            "/v1/admin/integrations/google/connect/callback",
            json={"code": "auth-code", "state": str(org.org_id)},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    assert response.status_code == 200
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert "refresh-logged" not in combined


@pytest.mark.anyio
async def test_import_sync_creates_external_blocks(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Import Org")
        owner = await saas_service.create_user(session, "owner@gcal-import.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_gcal(session, org.org_id)
        session.add(
            IntegrationsGoogleAccount(
                org_id=org.org_id,
                encrypted_refresh_token="refresh-token",
                token_scopes=["scope1"],
            )
        )
        session.add(
            IntegrationsGcalCalendar(
                org_id=org.org_id,
                calendar_id="primary",
                mode=GcalSyncMode.IMPORT,
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    events = [
        {
            "id": "evt-1",
            "summary": "Blocked",
            "start": {"dateTime": "2025-02-01T10:00:00Z"},
            "end": {"dateTime": "2025-02-01T11:00:00Z"},
        },
        {
            "id": "evt-2",
            "summary": "Out of office",
            "start": {"dateTime": "2025-02-02T09:00:00Z"},
            "end": {"dateTime": "2025-02-02T10:30:00Z"},
        },
    ]
    monkeypatch.setattr(gcal_service, "TOKEN_EXCHANGE_TRANSPORT", _transport_for_events(events))

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.post(
        "/v1/admin/integrations/google/gcal/import_sync",
        params={"from": "2025-02-01T00:00:00Z", "to": "2025-02-03T00:00:00Z"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200
    assert response.json()["imported"] == 2

    async with async_session_maker() as session:
        blocks = (
            await session.scalars(
                sa.select(ScheduleExternalBlock).where(ScheduleExternalBlock.org_id == org.org_id)
            )
        ).all()
        assert {block.external_event_id for block in blocks} == {"evt-1", "evt-2"}


@pytest.mark.anyio
async def test_import_sync_updates_existing_blocks(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Import Update Org")
        owner = await saas_service.create_user(session, "owner@gcal-import-update.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_gcal(session, org.org_id)
        session.add(
            IntegrationsGoogleAccount(
                org_id=org.org_id,
                encrypted_refresh_token="refresh-token",
                token_scopes=["scope1"],
            )
        )
        session.add(
            IntegrationsGcalCalendar(
                org_id=org.org_id,
                calendar_id="primary",
                mode=GcalSyncMode.IMPORT,
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    original_events = [
        {
            "id": "evt-1",
            "summary": "Blocked",
            "start": {"dateTime": "2025-03-01T10:00:00Z"},
            "end": {"dateTime": "2025-03-01T11:00:00Z"},
        }
    ]
    monkeypatch.setattr(gcal_service, "TOKEN_EXCHANGE_TRANSPORT", _transport_for_events(original_events))

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.post(
        "/v1/admin/integrations/google/gcal/import_sync",
        params={"from": "2025-03-01T00:00:00Z", "to": "2025-03-02T00:00:00Z"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200

    updated_events = [
        {
            "id": "evt-1",
            "summary": "Blocked Updated",
            "start": {"dateTime": "2025-03-01T12:00:00Z"},
            "end": {"dateTime": "2025-03-01T13:30:00Z"},
        }
    ]
    monkeypatch.setattr(gcal_service, "TOKEN_EXCHANGE_TRANSPORT", _transport_for_events(updated_events))

    response = client.post(
        "/v1/admin/integrations/google/gcal/import_sync",
        params={"from": "2025-03-01T00:00:00Z", "to": "2025-03-02T00:00:00Z"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200

    async with async_session_maker() as session:
        block = await session.scalar(
            sa.select(ScheduleExternalBlock).where(
                ScheduleExternalBlock.org_id == org.org_id,
                ScheduleExternalBlock.external_event_id == "evt-1",
            )
        )
        assert block is not None
        assert block.summary == "Blocked Updated"

        starts_at = block.starts_at
        ends_at = block.ends_at
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)

        assert starts_at == datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc)
        assert ends_at == datetime(2025, 3, 1, 13, 30, tzinfo=timezone.utc)


@pytest.mark.anyio
async def test_gcal_export_creates_event_and_mapping(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Export Org")
        owner = await saas_service.create_user(session, "owner@gcal-export.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_gcal(session, org.org_id)
        team = await _create_team(session, org.org_id, "export")
        booking = await _create_booking(
            session,
            org.org_id,
            team.team_id,
            datetime(2024, 8, 1, 16, 0, tzinfo=timezone.utc),
        )
        session.add(
            IntegrationsGoogleAccount(
                org_id=org.org_id,
                encrypted_refresh_token="refresh-export",
                token_scopes=["scope1"],
            )
        )
        session.add(
            IntegrationsGcalCalendar(
                org_id=org.org_id,
                calendar_id="primary",
                mode=GcalSyncMode.EXPORT,
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    _mock_access_token(monkeypatch)
    created: list[dict] = []
    updated: list[dict] = []
    _mock_gcal_client(monkeypatch, created, updated)

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.post(
        _export_url(booking.starts_at - timedelta(hours=1), booking.starts_at + timedelta(hours=1)),
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] == 1
    assert payload["updated"] == 0
    assert payload["skipped"] == 0
    assert len(created) == 1
    assert len(updated) == 0

    async with async_session_maker() as session:
        mapping = await session.scalar(
            sa.select(IntegrationsGcalEventMap).where(
                IntegrationsGcalEventMap.org_id == org.org_id,
                IntegrationsGcalEventMap.booking_id == booking.booking_id,
            )
        )
        assert mapping is not None
        assert mapping.external_event_id == "event-1"


@pytest.mark.anyio
async def test_gcal_export_is_idempotent(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Export Idempotent Org")
        owner = await saas_service.create_user(session, "owner@gcal-export-idem.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_gcal(session, org.org_id)
        team = await _create_team(session, org.org_id, "idempotent")
        booking = await _create_booking(
            session,
            org.org_id,
            team.team_id,
            datetime(2024, 8, 2, 16, 0, tzinfo=timezone.utc),
        )
        session.add(
            IntegrationsGoogleAccount(
                org_id=org.org_id,
                encrypted_refresh_token="refresh-idem",
                token_scopes=["scope1"],
            )
        )
        session.add(
            IntegrationsGcalCalendar(
                org_id=org.org_id,
                calendar_id="primary",
                mode=GcalSyncMode.EXPORT,
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    _mock_access_token(monkeypatch)
    created: list[dict] = []
    updated: list[dict] = []
    _mock_gcal_client(monkeypatch, created, updated)

    owner_token = saas_service.build_access_token(owner, membership)
    url = _export_url(booking.starts_at - timedelta(hours=1), booking.starts_at + timedelta(hours=1))
    first = client.post(url, headers={"Authorization": f"Bearer {owner_token}"})
    assert first.status_code == 200
    second = client.post(url, headers={"Authorization": f"Bearer {owner_token}"})
    assert second.status_code == 200

    assert first.json()["created"] == 1
    assert second.json()["skipped"] == 1
    assert len(created) == 1
    assert len(updated) == 0


@pytest.mark.anyio
async def test_gcal_export_updates_rescheduled_booking(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Export Reschedule Org")
        owner = await saas_service.create_user(session, "owner@gcal-export-resched.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_gcal(session, org.org_id)
        team = await _create_team(session, org.org_id, "reschedule")
        booking = await _create_booking(
            session,
            org.org_id,
            team.team_id,
            datetime(2024, 8, 3, 16, 0, tzinfo=timezone.utc),
        )
        session.add(
            IntegrationsGoogleAccount(
                org_id=org.org_id,
                encrypted_refresh_token="refresh-reschedule",
                token_scopes=["scope1"],
            )
        )
        session.add(
            IntegrationsGcalCalendar(
                org_id=org.org_id,
                calendar_id="primary",
                mode=GcalSyncMode.EXPORT,
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    _mock_access_token(monkeypatch)
    created: list[dict] = []
    updated: list[dict] = []
    _mock_gcal_client(monkeypatch, created, updated)

    owner_token = saas_service.build_access_token(owner, membership)
    url = _export_url(booking.starts_at - timedelta(hours=1), booking.starts_at + timedelta(hours=1))
    first = client.post(url, headers={"Authorization": f"Bearer {owner_token}"})
    assert first.status_code == 200

    async with async_session_maker() as session:
        booking_record = await session.get(Booking, booking.booking_id)
        booking_record.starts_at = booking_record.starts_at + timedelta(days=1)
        await session.commit()

    rescheduled_url = _export_url(
        booking.starts_at,
        booking.starts_at + timedelta(days=2),
    )
    second = client.post(rescheduled_url, headers={"Authorization": f"Bearer {owner_token}"})
    assert second.status_code == 200
    assert len(created) == 1
    assert len(updated) == 1
    assert updated[0]["event_id"] == "event-1"


@pytest.mark.anyio
async def test_gcal_export_dispatcher_allowed(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Export RBAC Org")
        dispatcher = await saas_service.create_user(session, "dispatcher@gcal-export.com", "secret")
        dispatcher_membership = await saas_service.create_membership(
            session, org, dispatcher, MembershipRole.DISPATCHER
        )
        viewer = await saas_service.create_user(session, "viewer@gcal-export.com", "secret")
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await _enable_gcal(session, org.org_id)
        team = await _create_team(session, org.org_id, "rbac")
        booking = await _create_booking(
            session,
            org.org_id,
            team.team_id,
            datetime(2024, 8, 4, 16, 0, tzinfo=timezone.utc),
        )
        session.add(
            IntegrationsGoogleAccount(
                org_id=org.org_id,
                encrypted_refresh_token="refresh-rbac",
                token_scopes=["scope1"],
            )
        )
        session.add(
            IntegrationsGcalCalendar(
                org_id=org.org_id,
                calendar_id="primary",
                mode=GcalSyncMode.EXPORT,
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    _mock_access_token(monkeypatch)
    created: list[dict] = []
    updated: list[dict] = []
    _mock_gcal_client(monkeypatch, created, updated)

    url = _export_url(booking.starts_at - timedelta(hours=1), booking.starts_at + timedelta(hours=1))

    dispatcher_token = saas_service.build_access_token(dispatcher, dispatcher_membership)
    dispatcher_resp = client.post(url, headers={"Authorization": f"Bearer {dispatcher_token}"})
    assert dispatcher_resp.status_code == 200

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    viewer_resp = client.post(url, headers={"Authorization": f"Bearer {viewer_token}"})
    assert viewer_resp.status_code == 403
