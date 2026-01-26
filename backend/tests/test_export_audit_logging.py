import uuid

import pytest
import sqlalchemy as sa

from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.data_rights import service as data_rights_service
from app.domain.data_rights.audit import (
    DATA_EXPORT_COMPLETED,
    DATA_EXPORT_DOWNLOAD_DENIED,
    DATA_EXPORT_DOWNLOADED,
    DATA_EXPORT_FAILED,
    DATA_EXPORT_REQUESTED,
    audit_data_export_event,
)
from app.domain.data_rights.db_models import DataExportRequest
from app.domain.leads.db_models import Lead
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.infra.storage import new_storage_backend
from app.infra.storage.backends import InMemoryStorageBackend
from app.jobs import data_export as data_export_job
from app.settings import settings


async def _create_org_with_member(async_session_maker, *, role: MembershipRole):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, f"Export Org {uuid.uuid4()}")
        email = f"export-{uuid.uuid4()}@example.com"
        user = await saas_service.create_user(session, email, "secret")
        membership = await saas_service.create_membership(session, org, user, role)
        await session.commit()
        return org, user, membership


async def _create_lead(async_session_maker, *, org_id: uuid.UUID, email: str) -> Lead:
    async with async_session_maker() as session:
        lead = Lead(
            org_id=org_id,
            name="Export Lead",
            phone="555-0100",
            email=email,
            postal_code="T5A",
            address="123 Export St",
            preferred_dates=["Mon"],
            structured_inputs={"beds": 2, "baths": 1, "cleaning_type": "standard"},
            estimate_snapshot={
                "price_cents": 10000,
                "subtotal_cents": 10000,
                "tax_cents": 0,
                "pricing_config_version": "v1",
                "config_hash": "hash",
                "line_items": [],
            },
            pricing_config_version="v1",
            config_hash="hash",
            referral_code=str(uuid.uuid4())[:8],
        )
        session.add(lead)
        await session.commit()
        await session.refresh(lead)
        return lead


async def _seed_completed_export(async_session_maker, *, org_id: uuid.UUID, subject_id: str) -> uuid.UUID:
    storage = new_storage_backend()
    key = f"data-exports/{org_id}/{uuid.uuid4()}.json"

    async def _body():
        yield b"{\"ok\":true}"

    stored = await storage.put(key=key, body=_body(), content_type="application/json")
    async with async_session_maker() as session:
        record = DataExportRequest(
            org_id=org_id,
            subject_id=subject_id,
            subject_type="lead",
            status="completed",
            storage_key=stored.key,
            content_type=stored.content_type,
            size_bytes=stored.size,
        )
        session.add(record)
        await session.flush()
        export_id = record.export_id
        await session.commit()
        return export_id


@pytest.mark.anyio
async def test_export_request_writes_audit_log(async_session_maker, client):
    org, user, membership = await _create_org_with_member(
        async_session_maker, role=MembershipRole.OWNER
    )
    lead = await _create_lead(
        async_session_maker, org_id=org.org_id, email="subject-export@example.com"
    )
    token = saas_service.build_access_token(user, membership)

    response = client.post(
        "/v1/data-rights/export-request",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req-export-1"},
        json={"lead_id": lead.lead_id},
    )
    assert response.status_code == 200
    export_id = response.json()["export_id"]

    async with async_session_maker() as session:
        log = await session.scalar(
            sa.select(AdminAuditLog).where(
                AdminAuditLog.action == DATA_EXPORT_REQUESTED,
                AdminAuditLog.resource_id == export_id,
                AdminAuditLog.org_id == org.org_id,
            )
        )
        assert log is not None
        assert log.action == DATA_EXPORT_REQUESTED
        context = log.context or {}
        assert context["actor_type"] == "admin"
        assert context["actor_id"] == str(user.user_id)
        assert context["subject_id"] == lead.lead_id
        assert context["request_id"] == "req-export-1"
        assert "subject_email" not in context
        assert context["on_behalf_of"]["subject_id"] == lead.lead_id


@pytest.mark.anyio
async def test_export_job_writes_completion_audit_logs(async_session_maker):
    org, _user, _membership = await _create_org_with_member(
        async_session_maker, role=MembershipRole.OWNER
    )
    lead = await _create_lead(
        async_session_maker, org_id=org.org_id, email="job-export@example.com"
    )
    async with async_session_maker() as session:
        await data_rights_service.create_data_export_request(
            session,
            org_id=org.org_id,
            subject_id=lead.lead_id,
            subject_type="lead",
            subject_email=lead.email,
            requested_by="tester",
            requested_by_type="admin",
            request_id="req-job-success",
        )
        await data_rights_service.create_data_export_request(
            session,
            org_id=org.org_id,
            subject_id="missing-lead",
            subject_type="lead",
            subject_email=None,
            requested_by="tester",
            requested_by_type="admin",
            request_id="req-job-fail",
        )
        await session.commit()

    async with async_session_maker() as session:
        await data_export_job.run_pending_data_exports(
            session, storage_backend=InMemoryStorageBackend()
        )

    async with async_session_maker() as session:
        completed_logs = (
            await session.execute(
                sa.select(AdminAuditLog).where(
                    AdminAuditLog.action == DATA_EXPORT_COMPLETED,
                    AdminAuditLog.org_id == org.org_id,
                )
            )
        ).scalars().all()
        failed_logs = (
            await session.execute(
                sa.select(AdminAuditLog).where(
                    AdminAuditLog.action == DATA_EXPORT_FAILED,
                    AdminAuditLog.org_id == org.org_id,
                )
            )
        ).scalars().all()
        assert completed_logs
        assert failed_logs
        completed_context = next(
            (log.context for log in completed_logs if (log.context or {}).get("request_id") == "req-job-success"),
            None,
        )
        failed_context = next(
            (log.context for log in failed_logs if (log.context or {}).get("request_id") == "req-job-fail"),
            None,
        )
        assert completed_context is not None
        assert failed_context is not None
        assert completed_context["actor_type"] == "system"
        assert completed_context["status"] == "completed"
        assert completed_context["size_bytes"] is not None
        assert failed_context["status"] == "failed"
        assert failed_context["error_code"] == "lead_not_found"
        assert "subject_email" not in completed_context
        assert "subject_email" not in failed_context


@pytest.mark.anyio
async def test_export_download_writes_audit_log(async_session_maker, client):
    org, user, membership = await _create_org_with_member(
        async_session_maker, role=MembershipRole.OWNER
    )
    lead = await _create_lead(
        async_session_maker, org_id=org.org_id, email="download-export@example.com"
    )
    export_id = await _seed_completed_export(
        async_session_maker, org_id=org.org_id, subject_id=lead.lead_id
    )
    token = saas_service.build_access_token(user, membership)

    response = client.get(
        f"/v1/data-rights/exports/{export_id}/download",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req-export-download"},
    )
    assert response.status_code == 200

    async with async_session_maker() as session:
        log = await session.scalar(
            sa.select(AdminAuditLog).where(
                AdminAuditLog.action == DATA_EXPORT_DOWNLOADED,
                AdminAuditLog.resource_id == str(export_id),
                AdminAuditLog.org_id == org.org_id,
            )
        )
        assert log is not None
        context = log.context or {}
        assert context["actor_type"] == "admin"
        assert context["request_id"] == "req-export-download"


@pytest.mark.anyio
async def test_export_download_denied_writes_audit_log(async_session_maker, client):
    org, user, membership = await _create_org_with_member(
        async_session_maker, role=MembershipRole.VIEWER
    )
    lead = await _create_lead(
        async_session_maker, org_id=org.org_id, email="denied-export@example.com"
    )
    export_id = await _seed_completed_export(
        async_session_maker, org_id=org.org_id, subject_id=lead.lead_id
    )
    token = saas_service.build_access_token(user, membership)

    response = client.get(
        f"/v1/data-rights/exports/{export_id}/download",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req-export-denied"},
    )
    assert response.status_code == 403

    async with async_session_maker() as session:
        log = await session.scalar(
            sa.select(AdminAuditLog).where(
                AdminAuditLog.action == DATA_EXPORT_DOWNLOAD_DENIED,
                AdminAuditLog.resource_id == str(export_id),
                AdminAuditLog.org_id == org.org_id,
            )
        )
        assert log is not None
        context = log.context or {}
        assert context["actor_type"] == "admin"
        assert context["reason_code"] == "missing_permission"


@pytest.mark.anyio
async def test_export_audit_logs_are_immutable(async_session_maker):
    export_id = uuid.uuid4()
    async with async_session_maker() as session:
        await audit_data_export_event(
            session,
            org_id=settings.default_org_id,
            export_id=export_id,
            subject_id="subject-1",
            subject_type="lead",
            actor_type="system",
            actor_id=None,
            request_id="req-immutability",
            event=DATA_EXPORT_REQUESTED,
        )
        await session.commit()

        log = await session.scalar(
            sa.select(AdminAuditLog).where(AdminAuditLog.resource_id == str(export_id))
        )
        assert log is not None
        log.action = "MUTATED"
        with pytest.raises(ValueError):
            await session.commit()
        await session.rollback()
