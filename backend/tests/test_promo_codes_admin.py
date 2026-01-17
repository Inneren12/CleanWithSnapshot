import asyncio
import base64
import uuid
from datetime import datetime, timezone

from app.domain.bookings.db_models import Booking
from app.domain.clients.db_models import ClientUser
from app.domain.marketing import db_models as marketing_db_models
from app.domain.saas.db_models import Organization
from app.settings import settings


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def _seed_org(async_session_maker, org_id: uuid.UUID, name: str) -> None:
    async with async_session_maker() as session:
        session.add(Organization(org_id=org_id, name=name))
        await session.commit()


async def _seed_client_booking(async_session_maker, org_id: uuid.UUID) -> tuple[str, str]:
    async with async_session_maker() as session:
        client = ClientUser(org_id=org_id, email="promo@example.com", name="Promo Client")
        session.add(client)
        await session.flush()
        booking = Booking(
            org_id=org_id,
            client_id=client.client_id,
            team_id=1,
            starts_at=datetime.now(tz=timezone.utc),
            duration_minutes=120,
            status="SCHEDULED",
        )
        session.add(booking)
        await session.commit()
        return client.client_id, booking.booking_id


async def _seed_redemption(async_session_maker, org_id: uuid.UUID, promo_id: uuid.UUID, client_id: str, booking_id: str) -> None:
    async with async_session_maker() as session:
        session.add(
            marketing_db_models.PromoCodeRedemption(
                org_id=org_id,
                promo_code_id=promo_id,
                client_id=client_id,
                booking_id=booking_id,
            )
        )
        await session.commit()


def test_promo_codes_rbac(client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.dispatcher_basic_username = "dispatcher"
    settings.dispatcher_basic_password = "dispatch"
    settings.legacy_basic_auth_enabled = True

    owner_headers = _auth_headers("owner", "secret")
    dispatcher_headers = _auth_headers("dispatcher", "dispatch")

    payload = {
        "code": "SAVE10",
        "name": "Save 10",
        "discount_type": "percent",
        "percent_off": 10,
        "active": True,
    }

    create_resp = client.post("/v1/admin/marketing/promo-codes", json=payload, headers=dispatcher_headers)
    assert create_resp.status_code == 403

    list_resp = client.get("/v1/admin/marketing/promo-codes", headers=dispatcher_headers)
    assert list_resp.status_code == 403

    owner_create = client.post("/v1/admin/marketing/promo-codes", json=payload, headers=owner_headers)
    assert owner_create.status_code == 201


def test_promo_codes_org_scoped(client, async_session_maker):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    org_id = uuid.uuid4()
    asyncio.run(_seed_org(async_session_maker, org_id, "Promo Org"))

    owner_headers = _auth_headers("owner", "secret")
    org_headers = {**owner_headers, "X-Test-Org": str(org_id)}

    payload = {
        "code": "ORGONLY",
        "name": "Org Only",
        "discount_type": "amount",
        "amount_cents": 2500,
        "active": True,
    }

    create_resp = client.post("/v1/admin/marketing/promo-codes", json=payload, headers=org_headers)
    assert create_resp.status_code == 201
    promo_id = create_resp.json()["promo_code_id"]

    list_default = client.get("/v1/admin/marketing/promo-codes", headers=owner_headers)
    assert list_default.status_code == 200
    assert all(item["promo_code_id"] != promo_id for item in list_default.json())

    get_default = client.get(f"/v1/admin/marketing/promo-codes/{promo_id}", headers=owner_headers)
    assert get_default.status_code == 404

    list_org = client.get("/v1/admin/marketing/promo-codes", headers=org_headers)
    assert list_org.status_code == 200
    assert any(item["promo_code_id"] == promo_id for item in list_org.json())


def test_promo_code_validation_restrictions(client, async_session_maker):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    owner_headers = _auth_headers("owner", "secret")

    payload = {
        "code": "WELCOME",
        "name": "Welcome",
        "discount_type": "percent",
        "percent_off": 15,
        "first_time_only": True,
        "one_per_customer": True,
        "min_order_cents": 20000,
        "usage_limit": 1,
        "active": True,
    }

    create_resp = client.post("/v1/admin/marketing/promo-codes", json=payload, headers=owner_headers)
    assert create_resp.status_code == 201
    promo_id = uuid.UUID(create_resp.json()["promo_code_id"])

    client_id, booking_id = asyncio.run(_seed_client_booking(async_session_maker, settings.default_org_id))
    asyncio.run(_seed_redemption(async_session_maker, settings.default_org_id, promo_id, client_id, booking_id))

    validate_payload = {
        "code": "WELCOME",
        "order_total_cents": 10000,
        "client_id": client_id,
        "booking_id": booking_id,
    }

    validate_resp = client.post(
        "/v1/admin/marketing/promo-codes/validate",
        json=validate_payload,
        headers=owner_headers,
    )
    assert validate_resp.status_code == 200
    data = validate_resp.json()
    assert data["eligible"] is False
    for reason in ["minimum_not_met", "not_first_time", "usage_limit_reached", "already_redeemed"]:
        assert reason in data["reasons"]
