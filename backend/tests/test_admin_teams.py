import base64
from datetime import date, datetime, timezone

import pytest

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import ensure_default_team
from app.domain.invoices.db_models import Invoice
from app.domain.workers.db_models import Worker
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def _reset_admin_creds():
    original = {
        "admin_basic_username": settings.admin_basic_username,
        "admin_basic_password": settings.admin_basic_password,
        "viewer_basic_username": settings.viewer_basic_username,
        "viewer_basic_password": settings.viewer_basic_password,
    }
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    settings.viewer_basic_username = "viewer"
    settings.viewer_basic_password = "secret"
    yield
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.mark.anyio
async def test_admin_can_create_team_and_booking_form_lists_teams(client, async_session_maker):
    async with async_session_maker() as session:
        default_team = await ensure_default_team(session)
        await session.commit()

    headers = _basic_auth("admin", "secret")
    create_resp = client.post(
        "/v1/admin/teams",
        headers=headers,
        json={"name": "Crew B"},
    )
    assert create_resp.status_code == 200

    list_resp = client.get("/v1/admin/teams", headers=headers)
    assert list_resp.status_code == 200
    payload = list_resp.json()
    team_names = {team["name"] for team in payload}
    assert default_team.name in team_names
    assert "Crew B" in team_names

    form_resp = client.get("/v1/admin/ui/bookings/new", headers=headers)
    assert form_resp.status_code == 200
    assert default_team.name in form_resp.text
    assert "Crew B" in form_resp.text


@pytest.mark.anyio
async def test_team_list_and_detail_shapes_are_permissioned(client, async_session_maker):
    unauth = client.get("/v1/admin/teams")
    assert unauth.status_code == 401

    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        worker = Worker(
            org_id=team.org_id,
            team_id=team.team_id,
            name="Lead One",
            phone="780-000-0000",
            role="Lead",
            rating_avg=4.6,
            rating_count=12,
            is_active=True,
        )
        booking = Booking(
            org_id=team.org_id,
            team_id=team.team_id,
            starts_at=datetime.now(tz=timezone.utc),
            duration_minutes=90,
            status="DONE",
            deposit_required=False,
            deposit_policy=[],
        )
        session.add_all([worker, booking])
        await session.flush()

        invoice = Invoice(
            org_id=team.org_id,
            invoice_number="INV-TEAM-1",
            order_id=booking.booking_id,
            status="SENT",
            issue_date=date.today(),
            currency="CAD",
            subtotal_cents=20000,
            taxable_subtotal_cents=0,
            tax_cents=0,
            total_cents=20000,
        )
        session.add(invoice)
        await session.commit()

    headers = _basic_auth("viewer", "secret")
    list_resp = client.get("/v1/admin/teams", headers=headers)
    assert list_resp.status_code == 200
    payload = list_resp.json()
    target = next((entry for entry in payload if entry["team_id"] == team.team_id), None)
    assert target is not None
    assert target["lead"]["name"] == "Lead One"
    assert "monthly_bookings" in target
    assert "monthly_revenue_cents" in target
    assert "rating_avg" in target

    detail_resp = client.get(f"/v1/admin/teams/{team.team_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["team_id"] == team.team_id
    assert "monthly_bookings" in detail
    assert "monthly_revenue_cents" in detail
