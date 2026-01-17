import uuid
from datetime import datetime, timezone

import pytest

from app.domain.bookings.db_models import Team
from app.domain.quality.db_models import QualityIssue, QualityIssueTag
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.domain.workers.db_models import Worker


@pytest.mark.anyio
async def test_quality_issue_tagging_persists(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Quality Tag Org")
        owner = await saas_service.create_user(session, "quality-tags@org.com", "secret")
        membership = await saas_service.create_membership(
            session, org, owner, MembershipRole.OWNER
        )
        issue = QualityIssue(
            id=uuid.uuid4(),
            org_id=org.org_id,
            status="open",
            summary="Late arrival",
        )
        session.add(issue)
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.patch(
        f"/v1/admin/quality/issues/{issue.id}/tags",
        headers={"Authorization": f"Bearer {token}"},
        json={"tag_keys": ["lateness", "communication"]},
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["issue_id"] == str(issue.id)
    assert [tag["tag_key"] for tag in payload["tags"]] == ["lateness", "communication"]

    detail_response = client.get(
        f"/v1/admin/quality/issues/{issue.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert [tag["tag_key"] for tag in detail_payload["tags"]] == [
        "lateness",
        "communication",
    ]


@pytest.mark.anyio
async def test_quality_common_issue_tags_analytics(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Quality Analytics Org")
        owner = await saas_service.create_user(session, "quality-analytics@org.com", "secret")
        membership = await saas_service.create_membership(
            session, org, owner, MembershipRole.OWNER
        )

        team = Team(org_id=org.org_id, name="Quality Team")
        session.add(team)
        await session.flush()

        worker_a = Worker(org_id=org.org_id, team_id=team.team_id, name="Worker A", phone="+10000000001")
        worker_b = Worker(org_id=org.org_id, team_id=team.team_id, name="Worker B", phone="+10000000002")
        session.add_all([worker_a, worker_b])
        await session.flush()

        issue_a = QualityIssue(
            id=uuid.uuid4(),
            org_id=org.org_id,
            status="open",
            summary="Late arrival",
            worker_id=worker_a.worker_id,
            created_at=datetime(2024, 1, 10, tzinfo=timezone.utc),
        )
        issue_b = QualityIssue(
            id=uuid.uuid4(),
            org_id=org.org_id,
            status="open",
            summary="Late again",
            worker_id=worker_a.worker_id,
            created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        )
        issue_c = QualityIssue(
            id=uuid.uuid4(),
            org_id=org.org_id,
            status="open",
            summary="Missed a spot",
            worker_id=worker_b.worker_id,
            created_at=datetime(2024, 1, 20, tzinfo=timezone.utc),
        )
        issue_outside = QualityIssue(
            id=uuid.uuid4(),
            org_id=org.org_id,
            status="open",
            summary="Outside range",
            worker_id=worker_b.worker_id,
            created_at=datetime(2023, 12, 15, tzinfo=timezone.utc),
        )
        session.add_all([issue_a, issue_b, issue_c, issue_outside])
        await session.flush()

        session.add_all(
            [
                QualityIssueTag(org_id=org.org_id, issue_id=issue_a.id, tag_key="lateness"),
                QualityIssueTag(org_id=org.org_id, issue_id=issue_b.id, tag_key="lateness"),
                QualityIssueTag(org_id=org.org_id, issue_id=issue_c.id, tag_key="missed_spots"),
                QualityIssueTag(org_id=org.org_id, issue_id=issue_outside.id, tag_key="communication"),
            ]
        )
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/quality/issues/common?from=2024-01-01&to=2024-01-31",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.json()
    payload = response.json()

    tags_by_key = {tag["tag_key"]: tag for tag in payload["tags"]}
    assert tags_by_key["lateness"]["issue_count"] == 2
    assert tags_by_key["lateness"]["worker_count"] == 1
    assert tags_by_key["lateness"]["workers"][0]["worker_name"] == "Worker A"
    assert tags_by_key["lateness"]["workers"][0]["issue_count"] == 2

    assert tags_by_key["missed_spots"]["issue_count"] == 1
    assert tags_by_key["missed_spots"]["worker_count"] == 1
    assert tags_by_key["missed_spots"]["workers"][0]["worker_name"] == "Worker B"
    assert "communication" not in tags_by_key
