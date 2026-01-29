import uuid

import pytest
from app.domain.clients.db_models import ClientUser
from app.domain.clients import service as client_service
from app.domain.data_rights.db_models import DataExportRequest
from app.domain.data_rights import service as data_rights_service
from app.domain.leads.db_models import Lead
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole, Organization
from app.infra.storage.backends import InMemoryStorageBackend
from app.jobs import data_export
from app.settings import settings


def _client_auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_lead(session, *, org_id: uuid.UUID, email: str) -> Lead:
    lead = Lead(
        org_id=org_id,
        name="Export Lead",
        phone="123",
        email=email,
        preferred_dates=[],
        structured_inputs={"beds": 1},
        estimate_snapshot={"total": 100},
        pricing_config_version="test",
        config_hash="hash",
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    return lead


async def _seed_client(session, *, org_id: uuid.UUID, email: str) -> ClientUser:
    client = ClientUser(org_id=org_id, email=email)
    session.add(client)
    await session.commit()
    await session.refresh(client)
    return client


@pytest.mark.anyio
async def test_export_request_creates_record(async_session_maker, client):
    async with async_session_maker() as session:
        lead = await _seed_lead(session, org_id=settings.default_org_id, email="subject@example.com")
        client_user = await _seed_client(session, org_id=settings.default_org_id, email=lead.email)

    token = client_service.issue_magic_token(
        email=client_user.email,
        client_id=client_user.client_id,
        secret=settings.client_portal_secret,
        ttl_minutes=settings.client_portal_token_ttl_minutes,
        org_id=settings.default_org_id,
    )
    response = client.post(
        "/v1/data-rights/export-request",
        headers=_client_auth_header(token),
    )
    assert response.status_code == 200
    payload = response.json()

    async with async_session_maker() as session:
        record = await session.get(DataExportRequest, uuid.UUID(payload["export_id"]))
        assert record is not None
        assert record.subject_email == "subject@example.com"
        assert record.subject_type == "client"
        assert record.status == "pending"


@pytest.mark.anyio
async def test_export_job_generates_bundle(async_session_maker):
    storage = InMemoryStorageBackend()
    async with async_session_maker() as session:
        lead = await _seed_lead(session, org_id=settings.default_org_id, email="bundle@example.com")
        record = await data_rights_service.create_data_export_request(
            session,
            org_id=settings.default_org_id,
            subject_id=lead.lead_id,
            subject_type="lead",
            subject_email=lead.email,
            requested_by="admin@example.com",
            requested_by_type="admin",
            request_id="req-123",
        )
        await session.commit()

        result = await data_export.run_pending_data_exports(session, storage_backend=storage)
        assert result["completed"] == 1

        await session.refresh(record)
        assert record.status == "completed"
        assert record.storage_key

    payload = await storage.read(key=record.storage_key)
    assert b"bundle@example.com" in payload


@pytest.mark.anyio
async def test_download_scoped_to_subject_and_admin(async_session_maker, client):
    storage = InMemoryStorageBackend()
    original_storage = getattr(client.app.state, "storage_backend", None)
    original_backend = settings.order_storage_backend
    client.app.state.storage_backend = storage
    settings.order_storage_backend = "memory"
    async with async_session_maker() as session:
        lead = await _seed_lead(session, org_id=settings.default_org_id, email="download@example.com")
        client_user = await _seed_client(session, org_id=settings.default_org_id, email=lead.email)
        record = await data_rights_service.create_data_export_request(
            session,
            org_id=settings.default_org_id,
            subject_id=client_user.client_id,
            subject_type="client",
            subject_email=client_user.email,
            requested_by=client_user.email,
            requested_by_type="client",
            request_id="req-download",
        )
        await session.commit()
        await data_export.run_pending_data_exports(session, storage_backend=storage)
        await session.refresh(record)

        org = await session.get(Organization, settings.default_org_id)
        admin_user = await saas_service.create_user(session, "accountant@example.com", "pw")
        membership = await saas_service.create_membership(session, org, admin_user, MembershipRole.ACCOUNTANT)
        await session.commit()

    try:
        token = client_service.issue_magic_token(
            email=client_user.email,
            client_id=client_user.client_id,
            secret=settings.client_portal_secret,
            ttl_minutes=settings.client_portal_token_ttl_minutes,
            org_id=settings.default_org_id,
        )
        subject_response = client.get(
            f"/v1/data-rights/exports/{record.export_id}/download",
            headers=_client_auth_header(token),
        )
        assert subject_response.status_code == 307

        admin_token = saas_service.build_access_token(admin_user, membership)
        admin_response = client.get(
            f"/v1/data-rights/exports/{record.export_id}/download",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_response.status_code == 307
    finally:
        client.app.state.storage_backend = original_storage
        settings.order_storage_backend = original_backend


@pytest.mark.anyio
async def test_cross_org_export_download_forbidden(async_session_maker, client):
    storage = InMemoryStorageBackend()
    original_storage = getattr(client.app.state, "storage_backend", None)
    client.app.state.storage_backend = storage
    async with async_session_maker() as session:
        org_b = await saas_service.create_organization(session, "Org B")
        lead_b = await _seed_lead(session, org_id=org_b.org_id, email="orgb@example.com")
        client_b = await _seed_client(session, org_id=org_b.org_id, email=lead_b.email)
        record = await data_rights_service.create_data_export_request(
            session,
            org_id=org_b.org_id,
            subject_id=client_b.client_id,
            subject_type="client",
            subject_email=client_b.email,
            requested_by=client_b.email,
            requested_by_type="client",
            request_id="req-orgb",
        )
        await session.commit()
        await data_export.run_pending_data_exports(session, storage_backend=storage)
        await session.refresh(record)

    try:
        token = client_service.issue_magic_token(
            email="other@example.com",
            client_id=str(uuid.uuid4()),
            secret=settings.client_portal_secret,
            ttl_minutes=settings.client_portal_token_ttl_minutes,
            org_id=settings.default_org_id,
        )
        response = client.get(
            f"/v1/data-rights/exports/{record.export_id}/download",
            headers=_client_auth_header(token),
        )
        assert response.status_code == 404
    finally:
        client.app.state.storage_backend = original_storage
