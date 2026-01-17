"""Tests for inventory low stock notifications."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inventory import schemas, service as inventory_service
from app.domain.inventory.db_models import InventoryItem
from app.domain.notifications_center.db_models import NotificationEvent, NotificationRulePreset
from app.settings import settings


async def _enable_low_stock_preset(session: AsyncSession) -> None:
    await session.execute(
        sa.delete(NotificationRulePreset).where(
            NotificationRulePreset.org_id == settings.default_org_id,
            NotificationRulePreset.preset_key == "low_stock",
        )
    )
    session.add(
        NotificationRulePreset(
            org_id=settings.default_org_id,
            preset_key="low_stock",
            enabled=True,
        )
    )
    await session.commit()


async def _create_item(
    session: AsyncSession,
    *,
    current_qty: Decimal,
    min_qty: Decimal,
) -> uuid.UUID:
    item = InventoryItem(
        item_id=uuid.uuid4(),
        org_id=settings.default_org_id,
        category_id=None,
        sku="LOW-001",
        name="Disinfectant",
        unit="bottles",
        current_qty=current_qty,
        min_qty=min_qty,
        location_label="Shelf L",
        active=True,
    )
    session.add(item)
    await session.commit()
    return item.item_id


async def _event_count(session: AsyncSession, item_id: uuid.UUID) -> int:
    result = await session.scalar(
        sa.select(sa.func.count())
        .select_from(NotificationEvent)
        .where(
            NotificationEvent.org_id == settings.default_org_id,
            NotificationEvent.type == "low_stock",
            NotificationEvent.entity_id == str(item_id),
        )
    )
    return int(result or 0)


@pytest.mark.anyio
async def test_low_stock_notification_emits_on_transition(async_session_maker):
    async with async_session_maker() as session:
        await _enable_low_stock_preset(session)
        item_id = await _create_item(session, current_qty=Decimal("10"), min_qty=Decimal("5"))

    async with async_session_maker() as session:
        await inventory_service.update_item(
            session,
            settings.default_org_id,
            item_id,
            schemas.InventoryItemUpdate(current_qty=Decimal("4")),
        )
        await session.commit()

    async with async_session_maker() as session:
        assert await _event_count(session, item_id) == 1


@pytest.mark.anyio
async def test_low_stock_notification_dedup_and_reemit(async_session_maker):
    async with async_session_maker() as session:
        await _enable_low_stock_preset(session)
        item_id = await _create_item(session, current_qty=Decimal("6"), min_qty=Decimal("5"))

    async with async_session_maker() as session:
        await inventory_service.update_item(
            session,
            settings.default_org_id,
            item_id,
            schemas.InventoryItemUpdate(current_qty=Decimal("4")),
        )
        await session.commit()
        assert await _event_count(session, item_id) == 1

        await inventory_service.update_item(
            session,
            settings.default_org_id,
            item_id,
            schemas.InventoryItemUpdate(current_qty=Decimal("3")),
        )
        await session.commit()
        assert await _event_count(session, item_id) == 1

        await inventory_service.update_item(
            session,
            settings.default_org_id,
            item_id,
            schemas.InventoryItemUpdate(current_qty=Decimal("6")),
        )
        await session.commit()
        assert await _event_count(session, item_id) == 1

        await inventory_service.update_item(
            session,
            settings.default_org_id,
            item_id,
            schemas.InventoryItemUpdate(current_qty=Decimal("4")),
        )
        await session.commit()
        assert await _event_count(session, item_id) == 2
