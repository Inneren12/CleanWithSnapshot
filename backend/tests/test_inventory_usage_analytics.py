"""Tests for inventory consumption analytics and gating."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking
from app.domain.feature_modules.db_models import OrgFeatureConfig
from app.domain.inventory.db_models import InventoryConsumption, InventoryItem
from app.domain.pricing_settings.db_models import ServiceType
from app.domain.saas.db_models import Organization
from app.main import app
from app.settings import settings

client = TestClient(app)

ADMIN_HEADERS = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}  # admin:admin123


@pytest.fixture
async def org_a(db_session: AsyncSession) -> Organization:
    org_id = settings.default_org_id
    org = await db_session.get(Organization, org_id)
    if org is None:
        org = Organization(org_id=org_id, name="Inventory Org")
        db_session.add(org)
    else:
        org.name = "Inventory Org"
    await db_session.commit()
    return org


async def _create_service_type(db_session: AsyncSession, org: Organization, name: str) -> ServiceType:
    service_type = ServiceType(org_id=org.org_id, name=name)
    db_session.add(service_type)
    await db_session.commit()
    await db_session.refresh(service_type)
    return service_type


async def _create_item(db_session: AsyncSession, org: Organization, name: str) -> InventoryItem:
    item = InventoryItem(
        item_id=uuid.uuid4(),
        org_id=org.org_id,
        category_id=None,
        sku=None,
        name=name,
        unit="bottles",
        current_qty=Decimal("10"),
        min_qty=Decimal("1"),
        location_label=None,
        active=True,
    )
    db_session.add(item)
    await db_session.commit()
    return item


async def _create_booking(db_session: AsyncSession, org: Organization) -> Booking:
    booking = Booking(
        booking_id=str(uuid.uuid4()),
        org_id=org.org_id,
        team_id=1,
        starts_at=datetime.now(timezone.utc),
        duration_minutes=60,
        status="CONFIRMED",
    )
    db_session.add(booking)
    await db_session.commit()
    return booking


@pytest.mark.anyio
async def test_usage_analytics_empty_returns_zero(org_a: Organization):
    response = client.get(
        "/v1/admin/inventory/usage_analytics",
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_consumption_cents"] == 0
    assert payload["cost_per_booking_avg_cents"] == 0
    assert payload["by_service_type"] == []
    assert payload["top_items"] == []


@pytest.mark.anyio
async def test_usage_analytics_math(org_a: Organization, db_session: AsyncSession):
    service_type_a = await _create_service_type(db_session, org_a, "Standard")
    service_type_b = await _create_service_type(db_session, org_a, "Deep")
    item_a = await _create_item(db_session, org_a, "Glass Cleaner")
    item_b = await _create_item(db_session, org_a, "Degreaser")
    booking_a = await _create_booking(db_session, org_a)
    booking_b = await _create_booking(db_session, org_a)

    db_session.add_all(
        [
            InventoryConsumption(
                consumption_id=uuid.uuid4(),
                org_id=org_a.org_id,
                booking_id=booking_a.booking_id,
                service_type_id=service_type_a.service_type_id,
                item_id=item_a.item_id,
                qty=Decimal("2"),
                unit_cost_cents=150,
                total_cost_cents=300,
                consumed_at=datetime.now(timezone.utc),
                recorded_by="admin",
            ),
            InventoryConsumption(
                consumption_id=uuid.uuid4(),
                org_id=org_a.org_id,
                booking_id=booking_a.booking_id,
                service_type_id=service_type_a.service_type_id,
                item_id=item_b.item_id,
                qty=Decimal("1"),
                unit_cost_cents=500,
                total_cost_cents=500,
                consumed_at=datetime.now(timezone.utc),
                recorded_by="admin",
            ),
            InventoryConsumption(
                consumption_id=uuid.uuid4(),
                org_id=org_a.org_id,
                booking_id=booking_b.booking_id,
                service_type_id=service_type_b.service_type_id,
                item_id=item_a.item_id,
                qty=Decimal("1"),
                unit_cost_cents=200,
                total_cost_cents=200,
                consumed_at=datetime.now(timezone.utc),
                recorded_by="admin",
            ),
        ]
    )
    await db_session.commit()

    response = client.get(
        "/v1/admin/inventory/usage_analytics",
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_consumption_cents"] == 1000
    assert payload["cost_per_booking_avg_cents"] == 500

    by_service = {entry["service_type_id"]: entry for entry in payload["by_service_type"]}
    assert by_service[service_type_a.service_type_id]["bookings"] == 1
    assert by_service[service_type_a.service_type_id]["consumption_cents"] == 800
    assert by_service[service_type_a.service_type_id]["cost_per_booking_cents"] == 800
    assert by_service[service_type_b.service_type_id]["bookings"] == 1
    assert by_service[service_type_b.service_type_id]["consumption_cents"] == 200
    assert by_service[service_type_b.service_type_id]["cost_per_booking_cents"] == 200

    top_items = {entry["item_id"]: entry for entry in payload["top_items"]}
    assert top_items[str(item_a.item_id)]["consumption_cents"] == 500
    assert top_items[str(item_b.item_id)]["consumption_cents"] == 500


@pytest.mark.anyio
async def test_usage_analytics_gated_by_feature(org_a: Organization, db_session: AsyncSession):
    org_id = org_a.org_id
    config = await db_session.get(OrgFeatureConfig, org_id)
    if config is None:
        config = OrgFeatureConfig(org_id=org_id, feature_overrides={})
        db_session.add(config)
    config.feature_overrides = {"inventory.usage_analytics": False}
    await db_session.commit()

    try:
        response = client.get(
            "/v1/admin/inventory/usage_analytics",
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 403
    finally:
        config.feature_overrides = {}
        await db_session.commit()
