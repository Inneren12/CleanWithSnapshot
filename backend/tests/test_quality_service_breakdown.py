import base64
import uuid
from datetime import date, datetime, timezone

import pytest

from app.domain.bookings.db_models import Booking, Team
from app.domain.clients.db_models import ClientFeedback, ClientUser
from app.domain.quality.db_models import QualityIssue
from app.domain.saas.db_models import Organization
from app.domain.workers.db_models import Worker
from app.settings import settings


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def admin_credentials():
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    settings.dispatcher_basic_username = "admin"
    settings.dispatcher_basic_password = "secret"
    yield


@pytest.mark.anyio
async def test_quality_service_breakdown_aggregates(client, async_session_maker):
    org_id = uuid.uuid4()
    from_date = date(2024, 1, 1)
    to_date = date(2024, 1, 31)

    async with async_session_maker() as session:
        session.add(Organization(org_id=org_id, name="Quality Org"))
        team = Team(org_id=org_id, name="Service Team")
        session.add(team)
        await session.flush()

        worker = Worker(org_id=org_id, team_id=team.team_id, name="Worker A", phone="+10000000001")
        client_user = ClientUser(org_id=org_id, email="client@example.com", name="Client A")
        session.add_all([worker, client_user])
        await session.flush()

        booking_deep = Booking(
            org_id=org_id,
            team_id=team.team_id,
            client_id=client_user.client_id,
            assigned_worker_id=worker.worker_id,
            starts_at=datetime(2024, 1, 10, tzinfo=timezone.utc),
            duration_minutes=120,
            status="DONE",
            policy_snapshot={"service_type": "Deep Clean"},
        )
        booking_deep_two = Booking(
            org_id=org_id,
            team_id=team.team_id,
            client_id=client_user.client_id,
            assigned_worker_id=worker.worker_id,
            starts_at=datetime(2024, 1, 11, tzinfo=timezone.utc),
            duration_minutes=90,
            status="DONE",
            policy_snapshot={"service_type": "Deep Clean"},
        )
        booking_standard = Booking(
            org_id=org_id,
            team_id=team.team_id,
            client_id=client_user.client_id,
            assigned_worker_id=worker.worker_id,
            starts_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            duration_minutes=60,
            status="DONE",
            policy_snapshot={"service_type": "Standard"},
        )
        session.add_all([booking_deep, booking_deep_two, booking_standard])
        await session.flush()

        session.add_all(
            [
                ClientFeedback(
                    org_id=org_id,
                    client_id=client_user.client_id,
                    booking_id=booking_deep.booking_id,
                    rating=5,
                    created_at=datetime(2024, 1, 10, tzinfo=timezone.utc),
                ),
                ClientFeedback(
                    org_id=org_id,
                    client_id=client_user.client_id,
                    booking_id=booking_deep_two.booking_id,
                    rating=4,
                    created_at=datetime(2024, 1, 11, tzinfo=timezone.utc),
                ),
                ClientFeedback(
                    org_id=org_id,
                    client_id=client_user.client_id,
                    booking_id=booking_standard.booking_id,
                    rating=3,
                    created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
                ),
            ]
        )

        session.add_all(
            [
                QualityIssue(
                    org_id=org_id,
                    booking_id=booking_deep.booking_id,
                    worker_id=worker.worker_id,
                    summary="Deep clean complaint",
                    rating=2,
                    status="open",
                    created_at=datetime(2024, 1, 12, tzinfo=timezone.utc),
                ),
                QualityIssue(
                    org_id=org_id,
                    booking_id=booking_standard.booking_id,
                    worker_id=worker.worker_id,
                    summary="Standard complaint",
                    rating=2,
                    status="open",
                    created_at=datetime(2024, 1, 16, tzinfo=timezone.utc),
                ),
                QualityIssue(
                    org_id=org_id,
                    worker_id=worker.worker_id,
                    summary="No booking complaint",
                    rating=1,
                    status="open",
                    created_at=datetime(2024, 1, 18, tzinfo=timezone.utc),
                ),
            ]
        )
        await session.commit()

    headers = {
        **_auth_headers("admin", "secret"),
        "X-Test-Org": str(org_id),
    }
    response = client.get(
        "/v1/admin/quality/services/breakdown",
        headers=headers,
        params={"from": from_date.isoformat(), "to": to_date.isoformat()},
    )
    assert response.status_code == 200
    payload = response.json()
    services = {entry["service_label"]: entry for entry in payload["services"]}

    deep_clean = services["Deep Clean"]
    assert deep_clean["review_count"] == 2
    assert deep_clean["complaint_count"] == 1
    assert deep_clean["average_rating"] == 4.5

    standard = services["Standard"]
    assert standard["review_count"] == 1
    assert standard["complaint_count"] == 1
    assert standard["average_rating"] == 3.0

    unspecified = services["Unspecified"]
    assert unspecified["review_count"] == 0
    assert unspecified["complaint_count"] == 1
    assert unspecified["average_rating"] is None


@pytest.mark.anyio
async def test_quality_summary_endpoints_scoped(client, async_session_maker):
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    async with async_session_maker() as session:
        session.add_all([Organization(org_id=org_a, name="Org A"), Organization(org_id=org_b, name="Org B")])
        team_a = Team(org_id=org_a, name="Team A")
        team_b = Team(org_id=org_b, name="Team B")
        session.add_all([team_a, team_b])
        await session.flush()

        worker_a = Worker(org_id=org_a, team_id=team_a.team_id, name="Worker A", phone="+10000000002")
        worker_b = Worker(org_id=org_b, team_id=team_b.team_id, name="Worker B", phone="+10000000003")
        client_a = ClientUser(org_id=org_a, email="client-a@example.com", name="Client A")
        client_b = ClientUser(org_id=org_b, email="client-b@example.com", name="Client B")
        session.add_all([worker_a, worker_b, client_a, client_b])
        await session.flush()

        booking_a = Booking(
            org_id=org_a,
            team_id=team_a.team_id,
            client_id=client_a.client_id,
            assigned_worker_id=worker_a.worker_id,
            starts_at=datetime(2024, 2, 10, tzinfo=timezone.utc),
            duration_minutes=90,
            status="DONE",
        )
        session.add(booking_a)
        await session.flush()

        session.add(
            ClientFeedback(
                org_id=org_a,
                client_id=client_a.client_id,
                booking_id=booking_a.booking_id,
                rating=5,
                comment="Great job",
                created_at=datetime(2024, 2, 10, tzinfo=timezone.utc),
            )
        )
        session.add(
            QualityIssue(
                org_id=org_a,
                booking_id=booking_a.booking_id,
                worker_id=worker_a.worker_id,
                client_id=client_a.client_id,
                summary="Minor complaint",
                rating=3,
                status="open",
                created_at=datetime(2024, 2, 12, tzinfo=timezone.utc),
            )
        )
        await session.commit()

    headers = {
        **_auth_headers("admin", "secret"),
        "X-Test-Org": str(org_a),
    }
    worker_response = client.get(
        f"/v1/admin/quality/workers/{worker_a.worker_id}/summary",
        headers=headers,
    )
    assert worker_response.status_code == 200
    worker_payload = worker_response.json()
    assert worker_payload["review_count"] == 1
    assert worker_payload["complaint_count"] == 1
    assert worker_payload["last_review"]["rating"] == 5

    client_response = client.get(
        f"/v1/admin/quality/clients/{client_a.client_id}/summary",
        headers=headers,
    )
    assert client_response.status_code == 200
    client_payload = client_response.json()
    assert client_payload["review_count"] == 1
    assert client_payload["complaint_count"] == 1
    assert client_payload["last_review"]["rating"] == 5

    scoped_worker = client.get(
        f"/v1/admin/quality/workers/{worker_b.worker_id}/summary",
        headers=headers,
    )
    assert scoped_worker.status_code == 404

    scoped_client = client.get(
        f"/v1/admin/quality/clients/{client_b.client_id}/summary",
        headers=headers,
    )
    assert scoped_client.status_code == 404
