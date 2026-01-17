import base64
import datetime as dt
import uuid

import pytest

from app.domain.bookings.db_models import Booking, TeamBlackout, Team
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.bookings.service import BUFFER_MINUTES, ensure_default_team
from app.domain.integrations.db_models import ScheduleExternalBlock
from app.domain.saas.db_models import Organization
from app.domain.workers.db_models import Worker
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


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
async def test_conflict_check_includes_external_blocks(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=2)
        session.add(
            ScheduleExternalBlock(
                org_id=team.org_id,
                source="gcal",
                external_event_id="evt-123",
                starts_at=start,
                ends_at=start + dt.timedelta(hours=2),
                summary="External hold",
            )
        )
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    params = {
        "starts_at": (start + dt.timedelta(minutes=30)).isoformat(),
        "ends_at": (start + dt.timedelta(minutes=90)).isoformat(),
        "team_id": team.team_id,
    }
    resp = client.get("/v1/admin/schedule/conflicts", headers=headers, params=params)
    assert resp.status_code == 200
    body = resp.json()
    kinds = {item["kind"] for item in body["conflicts"]}
    assert "external_block" in kinds


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
        session.add(
            ScheduleExternalBlock(
                org_id=other_org_id,
                source="gcal",
                external_event_id="other-org-event",
                starts_at=start,
                ends_at=start + dt.timedelta(hours=1),
                summary="Other org block",
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
