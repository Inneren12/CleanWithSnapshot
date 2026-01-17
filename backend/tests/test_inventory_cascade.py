"""Test inventory category deletion behavior - items should be preserved."""
import uuid

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

from app.domain.inventory.db_models import InventoryCategory, InventoryItem
from app.domain.saas.db_models import Organization
from app.infra.db import Base


@pytest.mark.anyio
async def test_deleting_category_preserves_items():
    """
    Regression test: When a category is deleted, inventory items should NOT be deleted.
    The DB FK has ondelete="SET NULL", so items.category_id should be set to NULL.
    The ORM relationship should use passive_deletes=True and NOT use delete-orphan cascade.
    """
    configure_mappers()

    # Create in-memory SQLite database with foreign keys enabled
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    # CRITICAL: Enable foreign keys for SQLite so ondelete="SET NULL" is enforced
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Create organization (only org_id and name are valid fields)
        org = Organization(
            org_id=uuid.uuid4(),
            name="Test Org",
        )
        session.add(org)
        await session.flush()

        # Create category
        category = InventoryCategory(
            category_id=uuid.uuid4(),
            org_id=org.org_id,
            name="Cleaning Supplies",
            sort_order=1,
        )
        session.add(category)
        await session.flush()

        # Create item linked to category
        item = InventoryItem(
            item_id=uuid.uuid4(),
            org_id=org.org_id,
            category_id=category.category_id,
            name="Glass Cleaner",
            unit="bottles",
        )
        session.add(item)
        await session.commit()

        # Store IDs for later verification
        category_id = category.category_id
        item_id = item.item_id

    # Delete category in a new session
    async with async_session() as session:
        result = await session.execute(
            select(InventoryCategory).where(InventoryCategory.category_id == category_id)
        )
        category_to_delete = result.scalar_one()
        await session.delete(category_to_delete)
        await session.commit()

    # Verify item still exists with category_id set to NULL
    async with async_session() as session:
        result = await session.execute(
            select(InventoryItem).where(InventoryItem.item_id == item_id)
        )
        preserved_item = result.scalar_one_or_none()

        # CRITICAL: Item must still exist
        assert preserved_item is not None, "InventoryItem was deleted when category was deleted!"

        # CRITICAL: category_id should be NULL (not deleted)
        assert preserved_item.category_id is None, (
            f"Expected category_id to be NULL, but got {preserved_item.category_id}"
        )

        # Verify item data is intact
        assert preserved_item.name == "Glass Cleaner"
        assert preserved_item.unit == "bottles"
        assert preserved_item.org_id == org.org_id

    await engine.dispose()


@pytest.mark.anyio
async def test_disassociating_category_preserves_items():
    """
    Test that clearing category.items collection doesn't delete items.
    This verifies delete-orphan is NOT in the cascade.
    """
    configure_mappers()

    # Create in-memory SQLite database with foreign keys enabled
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    # CRITICAL: Enable foreign keys for SQLite so ondelete="SET NULL" is enforced
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Create organization (only org_id and name are valid fields)
        org = Organization(
            org_id=uuid.uuid4(),
            name="Test Org",
        )
        session.add(org)
        await session.flush()

        # Create category
        category = InventoryCategory(
            category_id=uuid.uuid4(),
            org_id=org.org_id,
            name="Supplies",
        )
        session.add(category)
        await session.flush()

        # Create item linked to category
        item = InventoryItem(
            item_id=uuid.uuid4(),
            org_id=org.org_id,
            category_id=category.category_id,
            name="Mop",
            unit="pieces",
        )
        session.add(item)
        await session.commit()

        item_id = item.item_id
        category_id = category.category_id

    # Disassociate item from category by setting category_id to None
    async with async_session() as session:
        result = await session.execute(
            select(InventoryItem).where(InventoryItem.item_id == item_id)
        )
        item_to_update = result.scalar_one()

        # Set category_id to None (disassociate from category)
        item_to_update.category_id = None
        await session.commit()

    # Verify item still exists
    async with async_session() as session:
        result = await session.execute(
            select(InventoryItem).where(InventoryItem.item_id == item_id)
        )
        preserved_item = result.scalar_one_or_none()

        # Item should still exist (delete-orphan would have deleted it)
        assert preserved_item is not None, "Item was orphaned and deleted!"
        assert preserved_item.name == "Mop"

    await engine.dispose()


@pytest.mark.anyio
async def test_category_relationship_uses_passive_deletes():
    """
    Verify that the InventoryCategory.items relationship has passive_deletes=True.
    This ensures the DB handles the FK behavior, not the ORM.
    """
    configure_mappers()

    # Check relationship properties
    items_relationship = InventoryCategory.__mapper__.relationships["items"]

    # passive_deletes should be True
    assert items_relationship.passive_deletes is True, (
        "InventoryCategory.items relationship must have passive_deletes=True"
    )

    # Cascade should NOT include 'delete-orphan'
    cascade_str = str(items_relationship.cascade)
    assert "delete-orphan" not in cascade_str, (
        f"InventoryCategory.items relationship must NOT have delete-orphan cascade. "
        f"Current cascade: {cascade_str}"
    )

    # Cascade should include save-update and merge (standard)
    assert "save-update" in cascade_str, "Should include save-update cascade"
    assert "merge" in cascade_str, "Should include merge cascade"
