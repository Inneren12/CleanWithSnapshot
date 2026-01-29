from datetime import date, datetime, timezone

import pytest

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import ensure_default_team
from app.domain.invoices.db_models import Invoice
from app.domain.workers.db_models import Worker


@pytest.mark.anyio
async def test_admin_can_create_team_and_booking_form_lists_teams(admin_client, async_session_maker):
    async with async_session_maker() as session:
        default_team = await ensure_default_team(session)
        await session.commit()

    create_resp = admin_client.post("/v1/admin/teams", json={"name": "Crew B"})
    assert create_resp.status_code == 200

    list_resp = admin_client.get("/v1/admin/teams")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    team_names = {team["name"] for team in payload}
    assert default_team.name in team_names
    assert "Crew B" in team_names

    form_resp = admin_client.get("/v1/admin/ui/bookings/new")
    assert form_resp.status_code == 200
    assert default_team.name in form_resp.text
    assert "Crew B" in form_resp.text


@pytest.mark.anyio
async def test_team_list_and_detail_shapes_are_permissioned(
    anon_client, viewer_client, async_session_maker
):
    unauth = anon_client.get("/v1/admin/teams")
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

    list_resp = viewer_client.get("/v1/admin/teams")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    target = next((entry for entry in payload if entry["team_id"] == team.team_id), None)
    assert target is not None
    assert target["lead"]["name"] == "Lead One"
    assert "monthly_bookings" in target
    assert "monthly_revenue_cents" in target
    assert "rating_avg" in target

    detail_resp = viewer_client.get(f"/v1/admin/teams/{team.team_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["team_id"] == team.team_id
    assert "monthly_bookings" in detail
    assert "monthly_revenue_cents" in detail
