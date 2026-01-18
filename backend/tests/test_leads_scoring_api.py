import base64
import uuid

import pytest

from app.domain.feature_modules.db_models import OrgFeatureConfig
from app.domain.leads import statuses as lead_statuses
from app.domain.leads.db_models import Lead
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


async def _enable_scoring(async_session_maker, org_id: uuid.UUID) -> None:
    async with async_session_maker() as session:
        session.add(
            OrgFeatureConfig(
                org_id=org_id,
                feature_overrides={"module.leads": True, "leads.scoring": True},
            )
        )
        await session.commit()


async def _create_lead(async_session_maker, *, org_id: uuid.UUID) -> str:
    lead_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        lead = Lead(
            lead_id=lead_id,
            org_id=org_id,
            name="Score Lead",
            phone="780-555-0101",
            email="lead@example.com",
            postal_code="T5J 0N3",
            address="123 Score Lane",
            preferred_dates=["Mon morning"],
            access_notes=None,
            parking=None,
            pets=None,
            allergies=None,
            notes=None,
            structured_inputs={"beds": 3, "baths": 2, "cleaning_type": "deep"},
            estimate_snapshot={"total": 250},
            pricing_config_version="test",
            config_hash="test",
            status=lead_statuses.LEAD_STATUS_NEW,
            utm_source="google",
        )
        session.add(lead)
        await session.commit()
    return lead_id


@pytest.mark.anyio
async def test_scoring_rules_rbac_and_org_scope(async_session_maker, client):
    async with async_session_maker() as session:
        org_a = await saas_service.create_organization(session, "Scoring Org A")
        org_b = await saas_service.create_organization(session, "Scoring Org B")
        await session.commit()

    await _enable_scoring(async_session_maker, org_a.org_id)
    await _enable_scoring(async_session_maker, org_b.org_id)

    headers_admin_a = {**_auth_header("admin", "secret"), "X-Test-Org": str(org_a.org_id)}
    headers_admin_b = {**_auth_header("admin", "secret"), "X-Test-Org": str(org_b.org_id)}
    headers_viewer_a = {**_auth_header("viewer", "secret"), "X-Test-Org": str(org_a.org_id)}

    list_resp = client.get("/v1/admin/leads/scoring/rules", headers=headers_admin_a)
    assert list_resp.status_code == 200
    assert list_resp.json()["items"] == []

    forbidden_view = client.get("/v1/admin/leads/scoring/rules", headers=headers_viewer_a)
    assert forbidden_view.status_code == 403

    forbidden_patch = client.patch(
        "/v1/admin/leads/scoring/rules",
        headers=headers_viewer_a,
        json={"enabled": True, "rules": []},
    )
    assert forbidden_patch.status_code == 403

    create_resp = client.patch(
        "/v1/admin/leads/scoring/rules",
        headers=headers_admin_a,
        json={
            "enabled": True,
            "rules": [
                {
                    "key": "has_email",
                    "label": "Email provided",
                    "points": 10,
                    "conditions": [{"field": "email", "op": "exists"}],
                }
            ],
        },
    )
    assert create_resp.status_code == 200

    list_b = client.get("/v1/admin/leads/scoring/rules", headers=headers_admin_b)
    assert list_b.status_code == 200
    assert list_b.json()["items"] == []


@pytest.mark.anyio
async def test_scoring_recompute_snapshot(async_session_maker, client):
    async with async_session_maker() as session:
        org = Organization(org_id=uuid.uuid4(), name="Score Org")
        session.add(org)
        await session.commit()

    await _enable_scoring(async_session_maker, org.org_id)
    lead_id = await _create_lead(async_session_maker, org_id=org.org_id)

    headers_admin = {**_auth_header("admin", "secret"), "X-Test-Org": str(org.org_id)}

    rules_resp = client.patch(
        "/v1/admin/leads/scoring/rules",
        headers=headers_admin,
        json={
            "enabled": True,
            "rules": [
                {
                    "key": "has_email",
                    "label": "Email provided",
                    "points": 10,
                    "conditions": [{"field": "email", "op": "exists"}],
                },
                {
                    "key": "utm_google",
                    "label": "Google attribution",
                    "points": 5,
                    "conditions": [{"field": "utm_source", "op": "equals", "value": "google"}],
                },
                {
                    "key": "large_home",
                    "label": "Large home",
                    "points": 7,
                    "conditions": [{"field": "structured_inputs.beds", "op": "gte", "value": 3}],
                },
            ],
        },
    )
    assert rules_resp.status_code == 200

    recompute = client.post(
        f"/v1/admin/leads/{lead_id}/scoring/recompute",
        headers=headers_admin,
    )
    assert recompute.status_code == 200
    payload = recompute.json()
    assert payload["score"] == 22
    assert [reason["rule_key"] for reason in payload["reasons"]] == [
        "has_email",
        "utm_google",
        "large_home",
    ]
    assert payload["rules_version"] == rules_resp.json()["version"]

    get_resp = client.get(f"/v1/admin/leads/{lead_id}/scoring", headers=headers_admin)
    assert get_resp.status_code == 200
    assert get_resp.json()["score"] == 22

    async with async_session_maker() as session:
        other_org = await saas_service.create_organization(session, "Score Org B")
        await session.commit()
    await _enable_scoring(async_session_maker, other_org.org_id)

    headers_other = {**_auth_header("admin", "secret"), "X-Test-Org": str(other_org.org_id)}
    other_resp = client.get(f"/v1/admin/leads/{lead_id}/scoring", headers=headers_other)
    assert other_resp.status_code == 404
