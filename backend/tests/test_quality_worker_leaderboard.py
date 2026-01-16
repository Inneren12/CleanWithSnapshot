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
async def test_worker_quality_leaderboard_aggregates(client, async_session_maker):
    org_id = uuid.uuid4()
    team_name = "Quality Team A"
    from_date = date(2024, 1, 10)
    to_date = date(2024, 1, 20)

    async with async_session_maker() as session:
        session.add(Organization(org_id=org_id, name="Org A"))
        team = Team(org_id=org_id, name=team_name)
        session.add(team)
        await session.flush()

        worker_a = Worker(org_id=org_id, team_id=team.team_id, name="Alice Worker", phone="+10000000001")
        worker_b = Worker(org_id=org_id, team_id=team.team_id, name="Ben Worker", phone="+10000000002")
        session.add_all([worker_a, worker_b])

        client_user = ClientUser(org_id=org_id, email="client-a@example.com", name="Client A")
        session.add(client_user)
        await session.flush()

        booking_a1 = Booking(
            org_id=org_id,
            team_id=team.team_id,
            client_id=client_user.client_id,
            assigned_worker_id=worker_a.worker_id,
            starts_at=datetime(2024, 1, 12, tzinfo=timezone.utc),
            duration_minutes=60,
            status="DONE",
        )
        booking_a2 = Booking(
            org_id=org_id,
            team_id=team.team_id,
            client_id=client_user.client_id,
            assigned_worker_id=worker_a.worker_id,
            starts_at=datetime(2024, 1, 18, tzinfo=timezone.utc),
            duration_minutes=60,
            status="DONE",
        )
        booking_a_prev = Booking(
            org_id=org_id,
            team_id=team.team_id,
            client_id=client_user.client_id,
            assigned_worker_id=worker_a.worker_id,
            starts_at=datetime(2024, 1, 5, tzinfo=timezone.utc),
            duration_minutes=60,
            status="DONE",
        )
        booking_b = Booking(
            org_id=org_id,
            team_id=team.team_id,
            client_id=client_user.client_id,
            assigned_worker_id=worker_b.worker_id,
            starts_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            duration_minutes=60,
            status="DONE",
        )
        session.add_all([booking_a1, booking_a2, booking_a_prev, booking_b])
        await session.flush()

        feedback_entries = [
            ClientFeedback(
                org_id=org_id,
                client_id=client_user.client_id,
                booking_id=booking_a1.booking_id,
                rating=5,
                created_at=datetime(2024, 1, 12, tzinfo=timezone.utc),
            ),
            ClientFeedback(
                org_id=org_id,
                client_id=client_user.client_id,
                booking_id=booking_a2.booking_id,
                rating=4,
                created_at=datetime(2024, 1, 18, tzinfo=timezone.utc),
            ),
            ClientFeedback(
                org_id=org_id,
                client_id=client_user.client_id,
                booking_id=booking_b.booking_id,
                rating=3,
                created_at=datetime(2024, 1, 19, tzinfo=timezone.utc),
            ),
            ClientFeedback(
                org_id=org_id,
                client_id=client_user.client_id,
                booking_id=booking_a_prev.booking_id,
                rating=4,
                created_at=datetime(2024, 1, 5, tzinfo=timezone.utc),
            ),
        ]
        session.add_all(feedback_entries)

        issues = [
            QualityIssue(
                org_id=org_id,
                worker_id=worker_a.worker_id,
                summary="Missed detail",
                rating=2,
                status="open",
                created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            ),
            QualityIssue(
                org_id=org_id,
                worker_id=worker_a.worker_id,
                summary="Previous complaint",
                rating=3,
                status="open",
                created_at=datetime(2024, 1, 6, tzinfo=timezone.utc),
            ),
        ]
        session.add_all(issues)
        await session.commit()

    headers = {
        **_auth_headers("admin", "secret"),
        "X-Test-Org": str(org_id),
    }
    response = client.get(
        "/v1/admin/quality/workers/leaderboard",
        headers=headers,
        params={"from": from_date.isoformat(), "to": to_date.isoformat(), "include_trend": "true"},
    )
    assert response.status_code == 200
    payload = response.json()
    workers = {entry["worker_id"]: entry for entry in payload["workers"]}

    worker_a_entry = workers[worker_a.worker_id]
    assert worker_a_entry["review_count"] == 2
    assert worker_a_entry["complaint_count"] == 1
    assert worker_a_entry["average_rating"] == 4.5
    assert worker_a_entry["trend"]["previous_review_count"] == 1
    assert worker_a_entry["trend"]["review_count_delta"] == 1
    assert worker_a_entry["trend"]["complaint_count_delta"] == 0
    assert worker_a_entry["trend"]["average_rating_delta"] == 0.5

    worker_b_entry = workers[worker_b.worker_id]
    assert worker_b_entry["review_count"] == 1
    assert worker_b_entry["complaint_count"] == 0


@pytest.mark.anyio
async def test_worker_quality_leaderboard_org_scoping(client, async_session_maker):
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    async with async_session_maker() as session:
        session.add_all(
            [
                Organization(org_id=org_a, name="Org A"),
                Organization(org_id=org_b, name="Org B"),
            ]
        )
        team_a = Team(org_id=org_a, name="Scope Team A")
        team_b = Team(org_id=org_b, name="Scope Team B")
        session.add_all([team_a, team_b])
        await session.flush()

        worker_a = Worker(org_id=org_a, team_id=team_a.team_id, name="Ann", phone="+10000000003")
        worker_b = Worker(org_id=org_b, team_id=team_b.team_id, name="Bea", phone="+10000000004")
        session.add_all([worker_a, worker_b])

        client_a = ClientUser(org_id=org_a, email="client-scope-a@example.com", name="Client A")
        client_b = ClientUser(org_id=org_b, email="client-scope-b@example.com", name="Client B")
        session.add_all([client_a, client_b])
        await session.flush()

        booking_a = Booking(
            org_id=org_a,
            team_id=team_a.team_id,
            client_id=client_a.client_id,
            assigned_worker_id=worker_a.worker_id,
            starts_at=datetime(2024, 2, 10, tzinfo=timezone.utc),
            duration_minutes=60,
            status="DONE",
        )
        booking_b = Booking(
            org_id=org_b,
            team_id=team_b.team_id,
            client_id=client_b.client_id,
            assigned_worker_id=worker_b.worker_id,
            starts_at=datetime(2024, 2, 11, tzinfo=timezone.utc),
            duration_minutes=60,
            status="DONE",
        )
        session.add_all([booking_a, booking_b])
        await session.flush()

        session.add_all(
            [
                ClientFeedback(
                    org_id=org_a,
                    client_id=client_a.client_id,
                    booking_id=booking_a.booking_id,
                    rating=5,
                    created_at=datetime(2024, 2, 12, tzinfo=timezone.utc),
                ),
                ClientFeedback(
                    org_id=org_b,
                    client_id=client_b.client_id,
                    booking_id=booking_b.booking_id,
                    rating=1,
                    created_at=datetime(2024, 2, 12, tzinfo=timezone.utc),
                ),
                QualityIssue(
                    org_id=org_b,
                    worker_id=worker_b.worker_id,
                    summary="Org B complaint",
                    rating=1,
                    status="open",
                    created_at=datetime(2024, 2, 12, tzinfo=timezone.utc),
                ),
            ]
        )
        await session.commit()

    headers = {
        **_auth_headers("admin", "secret"),
        "X-Test-Org": str(org_a),
    }
    response = client.get(
        "/v1/admin/quality/workers/leaderboard",
        headers=headers,
        params={"from": "2024-02-10", "to": "2024-02-15"},
    )
    assert response.status_code == 200
    payload = response.json()
    worker_ids = {entry["worker_id"] for entry in payload["workers"]}
    assert worker_a.worker_id in worker_ids
    assert worker_b.worker_id not in worker_ids
