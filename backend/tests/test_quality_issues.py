import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.quality.db_models import QualityIssue
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole


@pytest.mark.anyio
async def test_quality_triage_groups_active_issues(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Quality Org")
        owner = await saas_service.create_user(session, "quality-owner@org.com", "secret")
        membership = await saas_service.create_membership(
            session, org, owner, MembershipRole.OWNER
        )

        critical_id = uuid.uuid4()
        medium_id = uuid.uuid4()
        resolved_id = uuid.uuid4()
        now = datetime.now(tz=timezone.utc)
        session.add_all(
            [
                QualityIssue(
                    id=critical_id,
                    org_id=org.org_id,
                    status="open",
                    severity=None,
                    rating=1,
                    summary="Missed area complaint",
                    created_at=now,
                ),
                QualityIssue(
                    id=medium_id,
                    org_id=org.org_id,
                    status="in_progress",
                    severity="medium",
                    rating=3,
                    summary="Late arrival issue",
                    created_at=now - timedelta(hours=1),
                ),
                QualityIssue(
                    id=resolved_id,
                    org_id=org.org_id,
                    status="resolved",
                    severity="low",
                    rating=5,
                    summary="Minor feedback",
                    created_at=now - timedelta(days=1),
                ),
            ]
        )
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/quality/issues/triage",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    buckets = {bucket["severity"]: bucket for bucket in payload["buckets"]}
    assert buckets["critical"]["total"] == 1
    assert buckets["medium"]["total"] == 1
    assert buckets["low"]["total"] == 0
    assert buckets["critical"]["items"][0]["id"] == str(critical_id)


@pytest.mark.anyio
async def test_quality_list_org_scoping(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Quality Org A")
        owner = await saas_service.create_user(session, "quality-a@org.com", "secret")
        membership = await saas_service.create_membership(
            session, org, owner, MembershipRole.OWNER
        )

        other_org = await saas_service.create_organization(session, "Quality Org B")

        issue_a = QualityIssue(
            id=uuid.uuid4(),
            org_id=org.org_id,
            status="open",
            severity="critical",
            rating=1,
            summary="Org A issue",
        )
        issue_b = QualityIssue(
            id=uuid.uuid4(),
            org_id=other_org.org_id,
            status="open",
            severity="critical",
            rating=1,
            summary="Org B issue",
        )
        session.add_all([issue_a, issue_b])
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/quality/issues",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(issue_a.id)


@pytest.mark.anyio
async def test_quality_rbac_blocks_viewer(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Quality RBAC Org")
        viewer = await saas_service.create_user(session, "quality-viewer@org.com", "secret")
        membership = await saas_service.create_membership(
            session, org, viewer, MembershipRole.VIEWER
        )
        await session.commit()

    token = saas_service.build_access_token(viewer, membership)
    response = client.get(
        "/v1/admin/quality/issues/triage",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
