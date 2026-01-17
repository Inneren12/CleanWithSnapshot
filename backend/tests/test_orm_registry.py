import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import configure_mappers

from app.domain.bookings.db_models import Booking, EmailEvent, Team
from app.domain.workers.db_models import Worker
from app.domain.inventory.db_models import (
    InventoryCategory,
    InventoryItem,
    InventorySupplier,
    PurchaseOrder,
    PurchaseOrderItem,
)
from app.infra.db import Base


@pytest.mark.anyio
async def test_booking_mapper_configures_without_worker_import():
    # Ensure string-based relationships resolve without manually importing related modules
    configure_mappers()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    assert any(rel.mapper.class_.__name__ == "Worker" for rel in Booking.__mapper__.relationships)

    await engine.dispose()


@pytest.mark.anyio
async def test_email_event_resolves_invoice_relationship():
    configure_mappers()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    assert any(rel.mapper.class_.__name__ == "Invoice" for rel in EmailEvent.__mapper__.relationships)

    await engine.dispose()


@pytest.mark.anyio
async def test_booking_resolves_order_addons_relationship():
    configure_mappers()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    assert any(
        rel.mapper.class_.__name__ == "OrderAddon" for rel in Booking.__mapper__.relationships
    )

    await engine.dispose()


@pytest.mark.anyio
async def test_team_worker_relationships_are_explicit():
    configure_mappers()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    team_workers_fk = Team.__mapper__.relationships["workers"]._calculated_foreign_keys
    assert Worker.__table__.c.team_id in team_workers_fk

    worker_team_fk = Worker.__mapper__.relationships["team"]._calculated_foreign_keys
    assert Worker.__table__.c.team_id in worker_team_fk

    team_lead_fk = Team.__mapper__.relationships["lead_worker"]._calculated_foreign_keys
    assert Team.__table__.c.lead_worker_id in team_lead_fk

    await engine.dispose()


@pytest.mark.anyio
async def test_inventory_tables_exist_in_metadata():
    """Test that inventory tables are registered."""
    configure_mappers()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Verify tables exist in metadata
    assert "inventory_categories" in Base.metadata.tables
    assert "inventory_items" in Base.metadata.tables
    assert "inventory_suppliers" in Base.metadata.tables
    assert "purchase_orders" in Base.metadata.tables
    assert "purchase_order_items" in Base.metadata.tables

    # Verify relationship between InventoryItem and InventoryCategory
    assert any(
        rel.mapper.class_.__name__ == "InventoryCategory"
        for rel in InventoryItem.__mapper__.relationships
    )

    assert InventorySupplier.__tablename__ in Base.metadata.tables
    assert PurchaseOrder.__tablename__ in Base.metadata.tables
    assert PurchaseOrderItem.__tablename__ in Base.metadata.tables

    await engine.dispose()
