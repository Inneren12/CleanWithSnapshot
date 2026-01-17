import asyncio
import base64
import uuid

from app.domain.bookings.db_models import Team
from app.domain.saas.db_models import Organization
from app.domain.training.db_models import TrainingAssignment, TrainingCourse
from app.domain.workers.db_models import Worker
from app.settings import settings


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_training_assignments_org_scoped(client, async_session_maker):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    headers = _auth_headers(settings.admin_basic_username, settings.admin_basic_password)

    other_org_id = uuid.uuid4()

    async def seed_data() -> int:
        async with async_session_maker() as session:
            org = Organization(org_id=other_org_id, name="Other Org")
            session.add(org)
            await session.flush()

            team = Team(org_id=other_org_id, name="Other Org Team")
            session.add(team)
            await session.flush()

            worker = Worker(
                org_id=other_org_id,
                team_id=team.team_id,
                name="Other Worker",
                phone="111-222-3333",
            )
            course = TrainingCourse(
                org_id=other_org_id,
                title="Other Course",
                description=None,
                duration_minutes=60,
                active=True,
                format="video",
            )
            session.add_all([worker, course])
            await session.flush()

            assignment = TrainingAssignment(
                org_id=other_org_id,
                course_id=course.course_id,
                worker_id=worker.worker_id,
                status="assigned",
            )
            session.add(assignment)
            await session.commit()
            return worker.worker_id

    other_worker_id = asyncio.run(seed_data())
    response = client.get(f"/v1/admin/training/workers/{other_worker_id}/assignments", headers=headers)
    assert response.status_code == 404


def test_training_rbac_rejects_course_create_for_dispatcher_and_viewer(client):
    settings.dispatcher_basic_username = "dispatcher"
    settings.dispatcher_basic_password = "dispatcher-secret"
    settings.viewer_basic_username = "viewer"
    settings.viewer_basic_password = "viewer-secret"

    payload = {
        "title": "Safety Orientation",
        "description": "Required onboarding safety basics.",
        "duration_minutes": 45,
        "active": True,
        "format": "video",
    }

    dispatcher_headers = _auth_headers(
        settings.dispatcher_basic_username, settings.dispatcher_basic_password
    )
    dispatcher_response = client.post(
        "/v1/admin/training/courses",
        headers=dispatcher_headers,
        json=payload,
    )
    assert dispatcher_response.status_code == 403

    viewer_headers = _auth_headers(settings.viewer_basic_username, settings.viewer_basic_password)
    viewer_response = client.post(
        "/v1/admin/training/courses",
        headers=viewer_headers,
        json=payload,
    )
    assert viewer_response.status_code == 403


def test_training_assignment_status_transitions(client, async_session_maker):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    headers = _auth_headers(settings.admin_basic_username, settings.admin_basic_password)

    async def seed_data() -> uuid.UUID:
        async with async_session_maker() as session:
            worker = Worker(
                team_id=1,
                name="Sam Runner",
                phone="555-0101",
            )
            course = TrainingCourse(
                title="Equipment Basics",
                description="Basics for equipment handling.",
                duration_minutes=30,
                active=True,
                format="doc",
            )
            session.add_all([worker, course])
            await session.flush()

            assignment = TrainingAssignment(
                course_id=course.course_id,
                worker_id=worker.worker_id,
                status="assigned",
            )
            session.add(assignment)
            await session.commit()
            return assignment.assignment_id

    assignment_id = asyncio.run(seed_data())
    complete_response = client.patch(
        f"/v1/admin/training/assignments/{assignment_id}",
        headers=headers,
        json={"status": "completed"},
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "completed"
    assert complete_response.json()["completed_at"] is not None

    invalid_response = client.patch(
        f"/v1/admin/training/assignments/{assignment_id}",
        headers=headers,
        json={"status": "in_progress"},
    )
    assert invalid_response.status_code == 400
