import base64
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.domain.bookings.db_models import Booking, Team
from app.domain.clients.db_models import ClientUser
from app.domain.feature_modules import service as feature_service
from app.domain.leads.db_models import Lead
from app.domain.nps import service as nps_service
from app.domain.nps.db_models import NpsResponse, SupportTicket
from app.domain.saas.db_models import Organization
from app.settings import settings


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _lead_payload(name: str = "Survey Lead", email: str = "survey@example.com") -> dict:
    return {
        "name": name,
        "phone": "780-555-9999",
        "email": email,
        "postal_code": "T5A",
        "address": "1 Test St",
        "preferred_dates": ["Mon"],
        "structured_inputs": {"beds": 1, "baths": 1, "cleaning_type": "standard"},
        "estimate_snapshot": {
            "price_cents": 12000,
            "subtotal_cents": 12000,
            "tax_cents": 0,
            "pricing_config_version": "v1",
            "config_hash": "hash",
            "line_items": [],
        },
        "pricing_config_version": "v1",
        "config_hash": "hash",
    }


def _seed_order(
    session_factory,
    order_id: str = "order-nps-1",
    *,
    email: str,
    org_id: UUID | None = None,
    team_id: int = 1,
) -> tuple[str, str, str]:
    async def _create():
        async with session_factory() as session:
            target_org = org_id or settings.default_org_id
            client = ClientUser(email=email, org_id=target_org)
            session.add(client)
            await session.flush()

            lead = Lead(**_lead_payload(email=email), org_id=target_org)
            session.add(lead)
            await session.flush()

            booking = Booking(
                booking_id=order_id,
                org_id=target_org,
                client_id=client.client_id,
                lead_id=lead.lead_id,
                team_id=team_id,
                starts_at=datetime.now(timezone.utc),
                duration_minutes=60,
                planned_minutes=60,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                consent_photos=False,
            )
            session.add(booking)
            await session.commit()
            return booking.booking_id, client.client_id, lead.lead_id

    return asyncio.run(_create())


def _seed_org(session_factory, name: str) -> tuple[UUID, int]:
    async def _create():
        async with session_factory() as session:
            org = Organization(name=name)
            session.add(org)
            await session.flush()
            team = Team(name=f"{name} Team", org_id=org.org_id)
            session.add(team)
            await session.commit()
            return org.org_id, team.team_id

    return asyncio.run(_create())


@pytest.fixture()
def admin_credentials():
    original_username = settings.admin_basic_username
    original_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    try:
        yield
    finally:
        settings.admin_basic_username = original_username
        settings.admin_basic_password = original_password


def test_nps_token_validation_and_single_response(client, async_session_maker):
    email = f"survey-{uuid4()}@example.com"
    order_id, _client_id, _ = _seed_order(async_session_maker, "order-nps-1", email=email)

    async def _create_token():
        async with async_session_maker() as session:
            await feature_service.upsert_org_feature_overrides(
                session, settings.default_org_id, {"quality.nps": True}
            )
            booking = await session.get(Booking, order_id)
            token_record = await nps_service.issue_nps_token(session, booking=booking)
            await session.commit()
            return token_record.token

    token = asyncio.run(_create_token())

    first = client.post(
        f"/v1/public/nps/{token}",
        json={"score": 8, "comment": "Great"},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "submitted"

    repeat = client.post(
        f"/v1/public/nps/{token}",
        json={"score": 9},
    )
    assert repeat.status_code == 200
    assert repeat.json()["status"] == "already_submitted"

    async def _verify_response():
        async with async_session_maker() as session:
            result = await session.execute(sa.select(NpsResponse))
            return result.scalars().all()

    saved = asyncio.run(_verify_response())
    assert len(saved) == 1
    assert saved[0].score == 8
    assert saved[0].order_id == order_id


def test_nps_token_expired(client, async_session_maker):
    email = f"survey-expired-{uuid4()}@example.com"
    order_id, _client_id, _ = _seed_order(async_session_maker, "order-nps-expired", email=email)

    async def _expire_token():
        async with async_session_maker() as session:
            await feature_service.upsert_org_feature_overrides(
                session, settings.default_org_id, {"quality.nps": True}
            )
            booking = await session.get(Booking, order_id)
            token_record = await nps_service.issue_nps_token(session, booking=booking)
            token_record.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
            await session.commit()
            return token_record.token

    token = asyncio.run(_expire_token())
    response = client.post(
        f"/v1/public/nps/{token}",
        json={"score": 7},
    )
    assert response.status_code == 400


def test_nps_token_org_scoping(client, async_session_maker):
    org_id, team_id = _seed_org(async_session_maker, "Org Scoped")
    email = f"survey-org-{uuid4()}@example.com"
    order_id, _client_id, _ = _seed_order(
        async_session_maker,
        "order-nps-org",
        email=email,
        org_id=org_id,
        team_id=team_id,
    )

    async def _mutate_token():
        async with async_session_maker() as session:
            await feature_service.upsert_org_feature_overrides(
                session, org_id, {"quality.nps": True}
            )
            booking = await session.get(Booking, order_id)
            token_record = await nps_service.issue_nps_token(session, booking=booking)
            token_record.org_id = settings.default_org_id
            await session.commit()
            return token_record.token

    token = asyncio.run(_mutate_token())
    response = client.post(
        f"/v1/public/nps/{token}",
        json={"score": 6},
    )
    assert response.status_code == 400


def test_low_score_creates_ticket_and_admin_api(client, async_session_maker, admin_credentials):
    email = f"survey-low-{uuid4()}@example.com"
    order_id, _client_id, _ = _seed_order(async_session_maker, "order-nps-2", email=email)

    async def _create_token():
        async with async_session_maker() as session:
            await feature_service.upsert_org_feature_overrides(
                session, settings.default_org_id, {"quality.nps": True}
            )
            booking = await session.get(Booking, order_id)
            token_record = await nps_service.issue_nps_token(session, booking=booking)
            await session.commit()
            return token_record.token

    token = asyncio.run(_create_token())

    submission = client.post(
        f"/v1/public/nps/{token}",
        json={"score": 2, "comment": "Needs work"},
    )
    assert submission.status_code == 200

    async def _fetch_ticket():
        async with async_session_maker() as session:
            result = await session.execute(
                sa.select(SupportTicket).where(SupportTicket.order_id == order_id)
            )
            return result.scalar_one_or_none()

    ticket = asyncio.run(_fetch_ticket())
    assert ticket is not None
    assert ticket.status == "OPEN"

    list_resp = client.get(
        "/api/admin/tickets",
        headers=_auth_headers(settings.admin_basic_username, settings.admin_basic_password),
    )
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["tickets"]
    first_ticket_id = body["tickets"][0]["id"]

    update = client.patch(
        f"/api/admin/tickets/{first_ticket_id}",
        json={"status": "IN_PROGRESS"},
        headers=_auth_headers(settings.admin_basic_username, settings.admin_basic_password),
    )
    assert update.status_code == 200
    assert update.json()["status"] == "IN_PROGRESS"


def test_admin_nps_segments_classification(client, async_session_maker, admin_credentials):
    emails = [f"survey-seg-{uuid4()}@example.com" for _ in range(4)]
    order_ids = [
        _seed_order(async_session_maker, f"order-nps-seg-{index}", email=email)[0]
        for index, email in enumerate(emails)
    ]

    async def _create_responses():
        async with async_session_maker() as session:
            await feature_service.upsert_org_feature_overrides(
                session, settings.default_org_id, {"quality.nps": True}
            )
            bookings = [await session.get(Booking, order_id) for order_id in order_ids]
            tokens = [
                await nps_service.issue_nps_token(session, booking=booking)
                for booking in bookings
                if booking is not None
            ]
            await nps_service.record_response(
                session, token_record=tokens[0], booking=bookings[0], score=10, comment="Amazing"
            )
            await nps_service.record_response(
                session, token_record=tokens[1], booking=bookings[1], score=8, comment="Solid"
            )
            await nps_service.record_response(
                session, token_record=tokens[2], booking=bookings[2], score=5, comment="Needs work"
            )
            await nps_service.record_response(
                session, token_record=tokens[3], booking=bookings[3], score=2, comment="Awful"
            )
            await session.commit()

    asyncio.run(_create_responses())

    response = client.get(
        "/v1/admin/nps/segments",
        headers=_auth_headers(settings.admin_basic_username, settings.admin_basic_password),
    )
    assert response.status_code == 200
    body = response.json()
    segments = body["segments"]
    assert segments["total_responses"] == 4
    assert segments["promoters"] == 1
    assert segments["passives"] == 1
    assert segments["detractors"] == 2
    assert segments["nps_score"] == -25.0
    detractors = body["top_detractors"]
    assert detractors
    scores = [entry["score"] for entry in detractors]
    assert all(score <= 6 for score in scores)
    assert scores == sorted(scores)


def test_admin_ticket_requires_auth(client, admin_credentials):
    response = client.get("/api/admin/tickets")
    assert response.status_code == 401
