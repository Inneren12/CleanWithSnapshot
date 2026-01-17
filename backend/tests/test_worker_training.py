import base64
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.bookings.db_models import Team
from app.domain.saas.db_models import Organization
from app.domain.training.db_models import TrainingRequirement, WorkerTrainingRecord
from app.domain.workers.db_models import Worker
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.mark.anyio
async def test_training_status_org_scoped(client, async_session_maker):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    async with async_session_maker() as session:
        session.add_all([Organization(org_id=org_a, name="Org A"), Organization(org_id=org_b, name="Org B")])
        await session.flush()
        team_a = Team(org_id=org_a, name="Team A")
        team_b = Team(org_id=org_b, name="Team B")
        session.add_all([team_a, team_b])
        await session.flush()
        worker = Worker(org_id=org_a, team_id=team_a.team_id, name="Worker A", phone="111")
        requirement = TrainingRequirement(org_id=org_a, key="whmis", title="WHMIS", active=True)
        session.add_all([worker, requirement])
        await session.flush()
        session.add(
            WorkerTrainingRecord(
                org_id=org_a,
                worker_id=worker.worker_id,
                requirement_id=requirement.requirement_id,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    headers = {**_basic_auth("admin", "secret"), "X-Test-Org": str(org_b)}
    response = client.get(
        f"/v1/admin/training/workers/{worker.worker_id}/status",
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_training_viewer_can_view_but_not_record(client, async_session_maker):
    original_viewer_username = settings.viewer_basic_username
    original_viewer_password = settings.viewer_basic_password
    settings.viewer_basic_username = "viewer"
    settings.viewer_basic_password = "secret"

    org_id = uuid.uuid4()
    async with async_session_maker() as session:
        session.add(Organization(org_id=org_id, name="Org Viewer"))
        await session.flush()
        team = Team(org_id=org_id, name="Team Viewer")
        session.add(team)
        await session.flush()
        worker = Worker(org_id=org_id, team_id=team.team_id, name="Worker Viewer", phone="222")
        requirement = TrainingRequirement(org_id=org_id, key="onboarding", title="Onboarding", active=True)
        session.add_all([worker, requirement])
        await session.commit()

    try:
        headers = {**_basic_auth("viewer", "secret"), "X-Test-Org": str(org_id)}
        view_response = client.get(
            f"/v1/admin/training/workers/{worker.worker_id}/status",
            headers=headers,
        )
        assert view_response.status_code == 200

        record_response = client.post(
            f"/v1/admin/training/workers/{worker.worker_id}/records",
            headers=headers,
            json={"requirement_key": "onboarding"},
        )
        assert record_response.status_code == 403
    finally:
        settings.viewer_basic_username = original_viewer_username
        settings.viewer_basic_password = original_viewer_password


@pytest.mark.anyio
async def test_training_status_due_and_overdue(client, async_session_maker):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    org_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with async_session_maker() as session:
        session.add(Organization(org_id=org_id, name="Org Training"))
        await session.flush()
        team = Team(org_id=org_id, name="Training Team")
        session.add(team)
        await session.flush()
        worker = Worker(org_id=org_id, team_id=team.team_id, name="Worker Training", phone="333")
        requirement_due = TrainingRequirement(org_id=org_id, key="onboarding", title="Onboarding", active=True)
        requirement_overdue = TrainingRequirement(org_id=org_id, key="whmis", title="WHMIS", active=True)
        requirement_ok = TrainingRequirement(org_id=org_id, key="safety", title="Safety", active=True)
        session.add_all([worker, requirement_due, requirement_overdue, requirement_ok])
        await session.flush()
        session.add_all(
            [
                WorkerTrainingRecord(
                    org_id=org_id,
                    worker_id=worker.worker_id,
                    requirement_id=requirement_overdue.requirement_id,
                    completed_at=now - timedelta(days=90),
                    expires_at=now - timedelta(days=1),
                ),
                WorkerTrainingRecord(
                    org_id=org_id,
                    worker_id=worker.worker_id,
                    requirement_id=requirement_ok.requirement_id,
                    completed_at=now - timedelta(days=5),
                    expires_at=now + timedelta(days=30),
                ),
            ]
        )
        await session.commit()

    headers = {**_basic_auth("admin", "secret"), "X-Test-Org": str(org_id)}
    response = client.get(
        f"/v1/admin/training/workers/{worker.worker_id}/status",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    status_by_key = {item["key"]: item["status"] for item in data["requirements"]}
    assert status_by_key["onboarding"] == "due"
    assert status_by_key["whmis"] == "overdue"
    assert status_by_key["safety"] == "ok"
