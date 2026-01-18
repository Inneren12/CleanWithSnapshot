import base64
import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from app.domain.feature_modules.db_models import OrgFeatureConfig
from app.domain.leads import statuses as lead_statuses
from app.domain.leads.db_models import Lead
from app.domain.leads_nurture.db_models import NurtureStepLog
from app.domain.leads_nurture.schemas import NurtureEnrollmentCreateRequest
from app.domain.leads_nurture.statuses import NurtureStepLogStatus
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import Organization
from app.settings import settings


def _auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def admin_credentials():
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    settings.viewer_basic_username = "viewer"
    settings.viewer_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True
    yield


async def _enable_nurture(async_session_maker, org_id: uuid.UUID) -> None:
    async with async_session_maker() as session:
        session.add(
            OrgFeatureConfig(
                org_id=org_id,
                feature_overrides={"module.leads": True, "leads.nurture": True},
            )
        )
        await session.commit()


async def _create_lead(async_session_maker, *, name: str, org_id: uuid.UUID) -> str:
    lead_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        lead = Lead(
            lead_id=lead_id,
            org_id=org_id,
            name=name,
            phone="780-555-0101",
            email=None,
            postal_code=None,
            address="123 Org Street",
            preferred_dates=["Mon morning"],
            access_notes=None,
            parking=None,
            pets=None,
            allergies=None,
            notes=None,
            structured_inputs={"beds": 1, "baths": 1, "cleaning_type": "standard"},
            estimate_snapshot={"total": 0},
            pricing_config_version="test",
            config_hash="test",
            status=lead_statuses.LEAD_STATUS_NEW,
        )
        session.add(lead)
        await session.commit()
    return lead_id


@pytest.mark.anyio
async def test_nurture_feature_gate_and_rbac(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Nurture Org")
        org_b = await saas_service.create_organization(session, "Nurture Org B")
        await session.commit()
    await _enable_nurture(async_session_maker, org.org_id)
    await _enable_nurture(async_session_maker, org_b.org_id)

    headers_admin = {**_auth_header("admin", "secret"), "X-Test-Org": str(org.org_id)}
    headers_viewer = {**_auth_header("viewer", "secret"), "X-Test-Org": str(org.org_id)}

    list_resp = client.get("/v1/admin/leads/nurture/campaigns", headers=headers_viewer)
    assert list_resp.status_code == 200

    create_resp = client.post(
        "/v1/admin/leads/nurture/campaigns",
        headers=headers_viewer,
        json={"key": "welcome", "name": "Welcome", "enabled": False},
    )
    assert create_resp.status_code == 403

    create_ok = client.post(
        "/v1/admin/leads/nurture/campaigns",
        headers=headers_admin,
        json={"key": "welcome", "name": "Welcome", "enabled": True},
    )
    assert create_ok.status_code == 201

    headers_admin_b = {**_auth_header("admin", "secret"), "X-Test-Org": str(org_b.org_id)}
    list_b = client.get("/v1/admin/leads/nurture/campaigns", headers=headers_admin_b)
    assert list_b.status_code == 200
    assert list_b.json()["items"] == []


@pytest.mark.anyio
async def test_nurture_feature_disabled(async_session_maker, client):
    async with async_session_maker() as session:
        org = Organization(org_id=uuid.uuid4(), name="Disabled Org")
        session.add(org)
        await session.commit()

    headers_admin = {**_auth_header("admin", "secret"), "X-Test-Org": str(org.org_id)}
    response = client.get("/v1/admin/leads/nurture/campaigns", headers=headers_admin)
    assert response.status_code == 403


@pytest.mark.anyio
async def test_enroll_creates_logs_and_idempotency(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Enroll Org")
        await session.commit()
    await _enable_nurture(async_session_maker, org.org_id)

    lead_id = await _create_lead(async_session_maker, name="Enroll Lead", org_id=org.org_id)
    headers_admin = {**_auth_header("admin", "secret"), "X-Test-Org": str(org.org_id)}

    campaign_resp = client.post(
        "/v1/admin/leads/nurture/campaigns",
        headers=headers_admin,
        json={"key": "post-lead", "name": "Post Lead", "enabled": True},
    )
    assert campaign_resp.status_code == 201
    campaign_id = campaign_resp.json()["campaign_id"]

    step_resp = client.post(
        f"/v1/admin/leads/nurture/campaigns/{campaign_id}/steps",
        headers=headers_admin,
        json={
            "step_index": 0,
            "delay_hours": 0,
            "channel": "log_only",
            "template_key": None,
            "payload_json": {"note": "first"},
            "active": True,
        },
    )
    assert step_resp.status_code == 201

    enroll_resp = client.post(
        f"/v1/admin/leads/{lead_id}/nurture/enroll",
        headers=headers_admin,
        json=NurtureEnrollmentCreateRequest(campaign_key="post-lead").model_dump(),
    )
    assert enroll_resp.status_code == 201
    payload = enroll_resp.json()
    assert payload["enrollment"]["lead_id"] == lead_id
    assert len(payload["planned_logs"]) == 1
    log = payload["planned_logs"][0]
    assert log["idempotency_key"].endswith(":0")

    status_resp = client.get(
        f"/v1/admin/leads/{lead_id}/nurture/status",
        headers=headers_admin,
    )
    assert status_resp.status_code == 200
    items = status_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["logs"][0]["idempotency_key"] == log["idempotency_key"]

    plan_resp = client.post(
        "/v1/admin/leads/nurture/plan",
        headers=headers_admin,
        params={"as_of": datetime.now(timezone.utc).isoformat()},
    )
    assert plan_resp.status_code == 200
    assert plan_resp.json()["items"][0]["idempotency_key"] == log["idempotency_key"]

    async with async_session_maker() as session:
        duplicate = NurtureStepLog(
            org_id=org.org_id,
            enrollment_id=uuid.UUID(payload["enrollment"]["enrollment_id"]),
            step_index=0,
            planned_at=datetime.now(timezone.utc),
            status=NurtureStepLogStatus.planned,
            idempotency_key=log["idempotency_key"],
        )
        session.add(duplicate)
        with pytest.raises(sa.exc.IntegrityError):
            await session.commit()
