import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import ensure_default_team
from app.domain.clients.db_models import ClientFeedback, ClientUser
from app.domain.quality.db_models import QualityIssue, QualityReviewReply
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.domain.workers.db_models import Worker


async def _seed_review_data(async_session_maker):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Review Org")
        owner = await saas_service.create_user(session, "review-owner@org.com", "secret")
        membership = await saas_service.create_membership(
            session, org, owner, MembershipRole.OWNER
        )
        team = await ensure_default_team(session, org_id=org.org_id)

        worker = Worker(
            org_id=org.org_id,
            team_id=team.team_id,
            name="Worker One",
            phone="555-1000",
            rating_avg=4.9,
            rating_count=10,
            is_active=True,
        )
        other_worker = Worker(
            org_id=org.org_id,
            team_id=team.team_id,
            name="Worker Two",
            phone="555-2000",
            rating_avg=4.2,
            rating_count=6,
            is_active=True,
        )
        session.add_all([worker, other_worker])
        await session.flush()

        client = ClientUser(
            org_id=org.org_id,
            email="client-one@example.com",
            name="Client One",
            phone="555-3000",
            address="123 Main St",
            is_active=True,
        )
        other_client = ClientUser(
            org_id=org.org_id,
            email="client-two@example.com",
            name="Client Two",
            phone="555-4000",
            address="456 Side St",
            is_active=True,
        )
        session.add_all([client, other_client])
        await session.flush()

        now = datetime.now(tz=timezone.utc)
        booking = Booking(
            org_id=org.org_id,
            team_id=team.team_id,
            client_id=client.client_id,
            assigned_worker_id=worker.worker_id,
            starts_at=now - timedelta(days=1),
            duration_minutes=90,
            status="DONE",
        )
        other_booking = Booking(
            org_id=org.org_id,
            team_id=team.team_id,
            client_id=other_client.client_id,
            assigned_worker_id=other_worker.worker_id,
            starts_at=now,
            duration_minutes=60,
            status="DONE",
        )
        session.add_all([booking, other_booking])
        await session.flush()

        feedback = ClientFeedback(
            org_id=org.org_id,
            client_id=client.client_id,
            booking_id=booking.booking_id,
            rating=5,
            comment="Fantastic service",
            created_at=now - timedelta(days=1),
        )
        other_feedback = ClientFeedback(
            org_id=org.org_id,
            client_id=other_client.client_id,
            booking_id=other_booking.booking_id,
            rating=3,
            comment="Okay job",
            created_at=now,
        )
        session.add_all([feedback, other_feedback])
        await session.flush()

        issue = QualityIssue(
            id=uuid.uuid4(),
            org_id=org.org_id,
            booking_id=booking.booking_id,
            client_id=client.client_id,
            rating=2,
            status="open",
            summary="Missed area",
        )
        session.add(issue)
        await session.commit()

        return {
            "org": org,
            "owner": owner,
            "membership": membership,
            "worker": worker,
            "client": client,
            "feedback": feedback,
            "other_feedback": other_feedback,
        }


@pytest.mark.anyio
async def test_quality_reviews_filters(async_session_maker, client):
    data = await _seed_review_data(async_session_maker)
    token = saas_service.build_access_token(data["owner"], data["membership"])

    response = client.get(
        "/v1/admin/quality/reviews?stars=5&has_issue=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["feedback_id"] == data["feedback"].feedback_id
    assert payload["items"][0]["has_issue"] is True

    response = client.get(
        f"/v1/admin/quality/reviews?worker_id={data['worker'].worker_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["feedback_id"] == data["feedback"].feedback_id


@pytest.mark.anyio
async def test_quality_review_reply_requires_permission(async_session_maker, client):
    data = await _seed_review_data(async_session_maker)
    async with async_session_maker() as session:
        viewer = await saas_service.create_user(session, "review-viewer@org.com", "secret")
        membership = await saas_service.create_membership(
            session, data["org"], viewer, MembershipRole.VIEWER
        )
        await session.commit()

    token = saas_service.build_access_token(viewer, membership)
    response = client.post(
        f"/v1/admin/quality/reviews/{data['feedback'].feedback_id}/reply",
        headers={"Authorization": f"Bearer {token}"},
        json={"template_key": "gratitude"},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_quality_review_reply_logged(async_session_maker, client):
    data = await _seed_review_data(async_session_maker)
    token = saas_service.build_access_token(data["owner"], data["membership"])
    response = client.post(
        f"/v1/admin/quality/reviews/{data['feedback'].feedback_id}/reply",
        headers={"Authorization": f"Bearer {token}"},
        json={"template_key": "gratitude"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["feedback_id"] == data["feedback"].feedback_id
    assert payload["template_key"] == "gratitude"
    assert payload["message"]

    async with async_session_maker() as session:
        reply = await session.scalar(
            sa.select(QualityReviewReply).where(
                QualityReviewReply.feedback_id == data["feedback"].feedback_id
            )
        )
        assert reply is not None
        assert reply.template_key == "gratitude"
