import base64
import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.bookings.db_models import Booking, TeamBlackout, Team
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.feature_modules.db_models import OrgFeatureConfig
from app.domain.bookings.service import BUFFER_MINUTES, ensure_default_team
from app.domain.org_settings import service as org_settings_service
from app.domain.saas.db_models import Organization
from app.domain.workers.db_models import Worker
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def _enable_schedule_optimization(session, org_id):
    record = await session.get(OrgFeatureConfig, org_id)
    overrides = dict(record.feature_overrides) if record and record.feature_overrides else {}
    overrides["schedule.optimization"] = True
    if record is None:
        record = OrgFeatureConfig(org_id=org_id, feature_overrides=overrides)
        session.add(record)
    else:
        record.feature_overrides = overrides


@pytest.fixture(autouse=True)
def _dispatch_creds():
    original_username = settings.dispatcher_basic_username
    original_password = settings.dispatcher_basic_password
    settings.dispatcher_basic_username = "dispatch"
    settings.dispatcher_basic_password = "secret"
    yield
    settings.dispatcher_basic_username = original_username
    settings.dispatcher_basic_password = original_password


@pytest.mark.anyio
async def test_conflict_check_catches_overlap(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=1)
        booking = Booking(
            team_id=team.team_id,
            starts_at=start,
            duration_minutes=90,
            status="PENDING",
        )
        session.add(booking)
        session.add(
            TeamBlackout(
                team_id=team.team_id,
                starts_at=start - dt.timedelta(minutes=30),
                ends_at=start + dt.timedelta(minutes=30),
                reason="maintenance",
            )
        )
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    params = {
        "starts_at": start.isoformat(),
        "ends_at": (start + dt.timedelta(minutes=60)).isoformat(),
        "team_id": team.team_id,
    }
    resp = client.get("/v1/admin/schedule/conflicts", headers=headers, params=params)
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_conflict"] is True
    kinds = {item["kind"] for item in body["conflicts"]}
    assert {"booking", "blackout"}.issubset(kinds)


@pytest.mark.anyio
async def test_conflict_check_includes_spanning_bookings(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        window_start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=1)
        window_end = window_start + dt.timedelta(minutes=60)
        spanning_start = window_start - dt.timedelta(minutes=45)

        overlapping_booking = Booking(
            team_id=team.team_id,
            starts_at=spanning_start,
            duration_minutes=120,
            status="CONFIRMED",
        )
        outside_booking = Booking(
            team_id=team.team_id,
            starts_at=window_end + dt.timedelta(minutes=BUFFER_MINUTES + 30),
            duration_minutes=45,
            status="CONFIRMED",
        )
        session.add_all([overlapping_booking, outside_booking])
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    params = {
        "starts_at": window_start.isoformat(),
        "ends_at": window_end.isoformat(),
        "team_id": team.team_id,
    }
    resp = client.get("/v1/admin/schedule/conflicts", headers=headers, params=params)
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_conflict"] is True
    references = {conflict["reference"] for conflict in body["conflicts"]}
    assert overlapping_booking.booking_id in references
    assert outside_booking.booking_id not in references


@pytest.mark.anyio
async def test_suggestions_filter_by_conflict_and_skill(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        secondary_team = Team(name="Secondary", org_id=team.org_id)
        session.add(secondary_team)
        await session.flush()
        available_worker = Worker(
            name="Available", phone="+1 555", team_id=team.team_id, email="a@example.com", role="deep clean", is_active=True
        )
        busy_worker = Worker(
            name="Busy", phone="+1 666", team_id=secondary_team.team_id, email="b@example.com", role="deep clean", is_active=True
        )
        other_skill = Worker(
            name="Other Skill", phone="+1 777", team_id=team.team_id, email="c@example.com", role="standard", is_active=True
        )
        session.add_all([available_worker, busy_worker, other_skill])
        await session.flush()

        conflict_start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=2)
        session.add(
            Booking(
                team_id=secondary_team.team_id,
                assigned_worker_id=busy_worker.worker_id,
                starts_at=conflict_start,
                duration_minutes=120,
                status="PENDING",
            )
        )
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    params = {
        "starts_at": conflict_start.isoformat(),
        "ends_at": (conflict_start + dt.timedelta(minutes=90)).isoformat(),
        "skill_tags": ["deep"],
    }
    resp = client.get("/v1/admin/schedule/suggestions", headers=headers, params=params)
    assert resp.status_code == 200
    body = resp.json()
    worker_names = {worker["name"] for worker in body["workers"]}
    assert "Available" in worker_names
    assert "Busy" not in worker_names
    assert "Other Skill" not in worker_names


@pytest.mark.anyio
async def test_suggestions_with_duration_min_returns_available_ranked_workers(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        secondary_team = Team(name="Secondary", org_id=team.org_id)
        session.add(secondary_team)
        await session.flush()
        available_worker = Worker(
            name="Available",
            phone="+1 555",
            team_id=team.team_id,
            email="available@example.com",
            role="standard",
            is_active=True,
        )
        busy_worker = Worker(
            name="Busy",
            phone="+1 666",
            team_id=secondary_team.team_id,
            email="busy@example.com",
            role="standard",
            is_active=True,
        )
        session.add_all([available_worker, busy_worker])
        await session.flush()

        start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=4)
        session.add(
            Booking(
                team_id=secondary_team.team_id,
                assigned_worker_id=busy_worker.worker_id,
                starts_at=start,
                duration_minutes=60,
                status="PENDING",
            )
        )
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    params = {
        "starts_at": start.isoformat(),
        "duration_min": 60,
    }
    resp = client.get("/v1/admin/schedule/suggestions", headers=headers, params=params)
    assert resp.status_code == 200
    body = resp.json()
    ranked_names = {worker["name"] for worker in body["ranked_workers"]}
    assert "Available" in ranked_names
    assert "Busy" not in ranked_names


@pytest.mark.anyio
async def test_conflicts_and_suggestions_are_org_scoped(client, async_session_maker):
    other_org_id = uuid.uuid4()
    async with async_session_maker() as session:
        default_team = await ensure_default_team(session)
        other_org = Organization(org_id=other_org_id, name="Other Org")
        session.add(other_org)
        await session.flush()

        other_team = Team(name="Other Org Team", org_id=other_org.org_id)
        session.add(other_team)
        await session.flush()
        start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=3)
        session.add(
            Booking(
                team_id=other_team.team_id,
                org_id=other_org_id,
                starts_at=start,
                duration_minutes=60,
                status="PENDING",
            )
        )
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    window = {
        "starts_at": start.isoformat(),
        "ends_at": (start + dt.timedelta(minutes=60)).isoformat(),
    }
    conflict_resp = client.get(
        "/v1/admin/schedule/conflicts",
        headers=headers,
        params={"team_id": default_team.team_id, **window},
    )
    assert conflict_resp.status_code == 200
    conflict_body = conflict_resp.json()
    assert conflict_body["has_conflict"] is False

    suggestion_resp = client.get("/v1/admin/schedule/suggestions", headers=headers, params=window)
    assert suggestion_resp.status_code == 200
    suggestion_body = suggestion_resp.json()
    team_ids = {team["team_id"] for team in suggestion_body["teams"]}
    assert default_team.team_id in team_ids
    assert all(team_id != other_team.team_id for team_id in team_ids)


@pytest.mark.anyio
async def test_schedule_optimization_suggestions_are_deterministic(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await _enable_schedule_optimization(session, team.org_id)
        worker = Worker(
            name="Scheduler",
            phone="+1 900",
            team_id=team.team_id,
            email="scheduler@example.com",
            role="standard",
            is_active=True,
        )
        session.add(worker)
        await session.flush()

        start_one = dt.datetime(2031, 1, 10, 9, 0, tzinfo=dt.timezone.utc)
        start_two = dt.datetime(2031, 1, 10, 13, 0, tzinfo=dt.timezone.utc)
        booking_one = Booking(
            booking_id="11111111-1111-1111-1111-111111111111",
            team_id=team.team_id,
            starts_at=start_one,
            duration_minutes=90,
            status="PENDING",
        )
        booking_two = Booking(
            booking_id="22222222-2222-2222-2222-222222222222",
            team_id=team.team_id,
            starts_at=start_two,
            duration_minutes=60,
            status="PENDING",
        )
        session.add_all([booking_one, booking_two])
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    params = {"from": "2031-01-10", "to": "2031-01-10"}
    resp = client.get("/v1/admin/schedule/optimization", headers=headers, params=params)
    assert resp.status_code == 200
    body = resp.json()
    ids = [item["id"] for item in body]
    assert ids == [
        "unassigned:11111111-1111-1111-1111-111111111111",
        "unassigned:22222222-2222-2222-2222-222222222222",
    ]
    assert body[0]["apply_payload"]["candidate_worker_ids"] == [worker.worker_id]


@pytest.mark.anyio
async def test_schedule_optimization_respects_org_timezone(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await _enable_schedule_optimization(session, team.org_id)
        org_settings = await org_settings_service.get_or_create_org_settings(session, team.org_id)
        org_settings.timezone = "America/Los_Angeles"
        booking_start = dt.datetime(2026, 1, 2, 6, 30, tzinfo=dt.timezone.utc)
        booking = Booking(
            booking_id="33333333-3333-3333-3333-333333333333",
            team_id=team.team_id,
            starts_at=booking_start,
            duration_minutes=60,
            status="PENDING",
        )
        session.add(booking)
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    params = {"from": "2026-01-01", "to": "2026-01-01"}
    resp = client.get("/v1/admin/schedule/optimization", headers=headers, params=params)
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body}
    assert "unassigned:33333333-3333-3333-3333-333333333333" in ids


@pytest.mark.anyio
async def test_schedule_optimization_apply_assigns_worker_and_audits(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await _enable_schedule_optimization(session, team.org_id)
        worker = Worker(
            name="Optimizer",
            phone="+1 333",
            team_id=team.team_id,
            email="optimizer@example.com",
            role="standard",
            is_active=True,
        )
        session.add(worker)
        await session.flush()

        start = dt.datetime(2032, 2, 2, 9, 0, tzinfo=dt.timezone.utc)
        booking = Booking(
            booking_id="44444444-4444-4444-4444-444444444444",
            team_id=team.team_id,
            starts_at=start,
            duration_minutes=60,
            status="PENDING",
        )
        session.add(booking)
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    payload = {
        "suggestion_id": f"unassigned:{booking.booking_id}",
        "apply_payload": {
            "action": "assign_worker",
            "booking_id": booking.booking_id,
            "team_id": booking.team_id,
            "starts_at": start.isoformat(),
            "ends_at": (start + dt.timedelta(minutes=60)).isoformat(),
            "candidate_worker_ids": [worker.worker_id],
            "worker_id": worker.worker_id,
        },
    }
    resp = client.post("/v1/admin/schedule/optimization/apply", headers=headers, json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["booking_id"] == booking.booking_id
    assert body[0]["worker_id"] == worker.worker_id

    async with async_session_maker() as session:
        updated = await session.get(Booking, booking.booking_id)
        assert updated.assigned_worker_id == worker.worker_id
        audit = (
            await session.execute(
                select(AdminAuditLog).where(
                    AdminAuditLog.action == "SCHEDULE_OPTIMIZATION_APPLY",
                    AdminAuditLog.resource_id == booking.booking_id,
                )
            )
        ).scalar_one_or_none()
        assert audit is not None


@pytest.mark.anyio
async def test_schedule_optimization_apply_conflict_returns_409(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await _enable_schedule_optimization(session, team.org_id)
        worker = Worker(
            name="Busy Optimizer",
            phone="+1 444",
            team_id=team.team_id,
            email="busy@example.com",
            role="standard",
            is_active=True,
        )
        session.add(worker)
        await session.flush()

        start = dt.datetime(2032, 3, 3, 10, 0, tzinfo=dt.timezone.utc)
        session.add(
            Booking(
                booking_id="55555555-5555-5555-5555-555555555555",
                team_id=team.team_id,
                assigned_worker_id=worker.worker_id,
                starts_at=start,
                duration_minutes=90,
                status="CONFIRMED",
            )
        )
        booking = Booking(
            booking_id="66666666-6666-6666-6666-666666666666",
            team_id=team.team_id,
            starts_at=start,
            duration_minutes=60,
            status="PENDING",
        )
        session.add(booking)
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    payload = {
        "suggestion_id": f"unassigned:{booking.booking_id}",
        "apply_payload": {
            "action": "assign_worker",
            "booking_id": booking.booking_id,
            "team_id": booking.team_id,
            "starts_at": start.isoformat(),
            "ends_at": (start + dt.timedelta(minutes=60)).isoformat(),
            "candidate_worker_ids": [worker.worker_id],
            "worker_id": worker.worker_id,
        },
    }
    resp = client.post("/v1/admin/schedule/optimization/apply", headers=headers, json=payload)
    assert resp.status_code == 409
    body = resp.json()
    assert body["errors"][0]["reason"] == "conflict"

    async with async_session_maker() as session:
        updated = await session.get(Booking, booking.booking_id)
        assert updated.assigned_worker_id is None

@pytest.mark.anyio
async def test_quick_create_requires_booking_permission(client, async_session_maker):
    original_viewer_user = settings.viewer_basic_username
    original_viewer_pass = settings.viewer_basic_password
    settings.viewer_basic_username = "viewer"
    settings.viewer_basic_password = "viewer-secret"
    try:
        async with async_session_maker() as session:
            client_user = ClientUser(
                org_id=settings.default_org_id,
                email="viewer-client@example.com",
                name="Viewer Client",
                phone="555-0101",
            )
            session.add(client_user)
            await session.flush()
            address = ClientAddress(
                org_id=settings.default_org_id,
                client_id=client_user.client_id,
                label="Home",
                address_text="123 Main St",
                is_active=True,
            )
            session.add(address)
            await session.commit()

        headers = _basic_auth("viewer", "viewer-secret")
        start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=2)
        payload = {
            "starts_at": start.isoformat(),
            "duration_minutes": 90,
            "client_id": client_user.client_id,
            "address_id": address.address_id,
            "price_cents": 12500,
            "deposit_cents": 0,
        }
        resp = client.post("/v1/admin/schedule/quick-create", headers=headers, json=payload)
        assert resp.status_code == 403
    finally:
        settings.viewer_basic_username = original_viewer_user
        settings.viewer_basic_password = original_viewer_pass


@pytest.mark.anyio
async def test_quick_create_booking_happy_path(client, async_session_maker):
    headers = _basic_auth(
        settings.admin_basic_username or "admin",
        settings.admin_basic_password or "admin123",
    )
    start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=2)
    start = start.replace(hour=18, minute=0, second=0, microsecond=0)
    payload = {
        "starts_at": start.isoformat(),
        "duration_minutes": 120,
        "client": {
            "name": "E2E Schedule Client",
            "email": f"schedule-client-{uuid.uuid4()}@example.com",
            "phone": "555-0101",
        },
        "address_text": "123 Main St",
        "price_cents": 15000,
        "addon_ids": [],
    }

    resp = client.post("/v1/admin/schedule/quick-create", headers=headers, json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["booking_id"]
    async with async_session_maker() as session:
        booking = await session.get(Booking, body["booking_id"])
        assert booking is not None
        assert booking.client_id is not None
        assert booking.status == "PENDING"


@pytest.mark.anyio
async def test_quick_create_booking_slot_unavailable_returns_409(client):
    headers = _basic_auth(
        settings.admin_basic_username or "admin",
        settings.admin_basic_password or "admin123",
    )
    start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=2)
    start = start.replace(hour=18, minute=17, second=0, microsecond=0)
    payload = {
        "starts_at": start.isoformat(),
        "duration_minutes": 120,
        "client": {
            "name": "E2E Schedule Client",
            "email": f"schedule-client-{uuid.uuid4()}@example.com",
            "phone": "555-0101",
        },
        "address_text": "123 Main St",
        "price_cents": 15000,
        "addon_ids": [],
    }

    resp = client.post("/v1/admin/schedule/quick-create", headers=headers, json=payload)
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_quick_create_booking_missing_org_returns_404(client):
    headers = {
        **_basic_auth(
            settings.admin_basic_username or "admin",
            settings.admin_basic_password or "admin123",
        ),
        "X-Test-Org": str(uuid.uuid4()),
    }
    start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=2)
    start = start.replace(hour=18, minute=0, second=0, microsecond=0)
    payload = {
        "starts_at": start.isoformat(),
        "duration_minutes": 120,
        "client": {
            "name": "E2E Schedule Client",
            "email": f"schedule-client-{uuid.uuid4()}@example.com",
            "phone": "555-0101",
        },
        "address_text": "123 Main St",
        "price_cents": 15000,
        "addon_ids": [],
    }

    resp = client.post("/v1/admin/schedule/quick-create", headers=headers, json=payload)
    assert resp.status_code == 404
