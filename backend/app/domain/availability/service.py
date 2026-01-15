from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.availability import schemas
from app.domain.bookings.db_models import AvailabilityBlock, Team
from app.domain.workers.db_models import Worker


def _normalize(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _validate_scope(scope_type: str, scope_id: int | None, block_type: str) -> None:
    if scope_type not in {"worker", "team", "org"}:
        raise ValueError("invalid_scope_type")
    if block_type not in {"vacation", "sick", "training", "holiday"}:
        raise ValueError("invalid_block_type")
    if scope_type == "org" and scope_id is not None:
        raise ValueError("org_scope_disallows_scope_id")
    if scope_type in {"worker", "team"} and scope_id is None:
        raise ValueError("scope_id_required")
    if block_type == "holiday" and scope_type != "org":
        raise ValueError("holiday_requires_org_scope")


async def _ensure_scope_entity(session: AsyncSession, org_id, scope_type: str, scope_id: int | None) -> None:
    if scope_type == "org":
        return
    if scope_type == "team":
        team = await session.get(Team, scope_id)
        if team is None or team.org_id != org_id:
            raise LookupError("team_not_found")
        return
    if scope_type == "worker":
        worker = await session.get(Worker, scope_id)
        if worker is None or worker.org_id != org_id:
            raise LookupError("worker_not_found")
        return


async def list_blocks(
    session: AsyncSession,
    org_id,
    *,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    scope_type: str | None = None,
    scope_id: int | None = None,
) -> list[AvailabilityBlock]:
    stmt = select(AvailabilityBlock).where(AvailabilityBlock.org_id == org_id)
    if starts_at is not None:
        stmt = stmt.where(AvailabilityBlock.ends_at > _normalize(starts_at))
    if ends_at is not None:
        stmt = stmt.where(AvailabilityBlock.starts_at < _normalize(ends_at))
    if scope_type is not None:
        stmt = stmt.where(AvailabilityBlock.scope_type == scope_type)
    if scope_id is not None:
        stmt = stmt.where(AvailabilityBlock.scope_id == scope_id)
    stmt = stmt.order_by(AvailabilityBlock.starts_at.asc())
    return list((await session.execute(stmt)).scalars().all())


async def create_block(
    session: AsyncSession,
    org_id,
    *,
    payload: schemas.AvailabilityBlockCreate,
    created_by: str | None = None,
) -> AvailabilityBlock:
    normalized_start = _normalize(payload.starts_at)
    normalized_end = _normalize(payload.ends_at)
    if normalized_end <= normalized_start:
        raise ValueError("invalid_window")
    _validate_scope(payload.scope_type, payload.scope_id, payload.block_type)
    await _ensure_scope_entity(session, org_id, payload.scope_type, payload.scope_id)

    block = AvailabilityBlock(
        org_id=org_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        block_type=payload.block_type,
        starts_at=normalized_start,
        ends_at=normalized_end,
        reason=payload.reason,
        created_by=created_by,
    )
    session.add(block)
    await session.commit()
    await session.refresh(block)
    return block


async def update_block(
    session: AsyncSession,
    org_id,
    block_id: int,
    *,
    payload: schemas.AvailabilityBlockUpdate,
    reason_set: bool = False,
) -> AvailabilityBlock:
    block = await session.get(AvailabilityBlock, block_id)
    if block is None or block.org_id != org_id:
        raise LookupError("block_not_found")

    updated_scope_type = payload.scope_type or block.scope_type
    if payload.scope_id is not None:
        updated_scope_id = payload.scope_id
    elif payload.scope_type == "org":
        updated_scope_id = None
    else:
        updated_scope_id = block.scope_id
    updated_block_type = payload.block_type or block.block_type
    updated_starts_at = _normalize(payload.starts_at) if payload.starts_at else block.starts_at
    updated_ends_at = _normalize(payload.ends_at) if payload.ends_at else block.ends_at

    if updated_ends_at <= updated_starts_at:
        raise ValueError("invalid_window")
    _validate_scope(updated_scope_type, updated_scope_id, updated_block_type)
    await _ensure_scope_entity(session, org_id, updated_scope_type, updated_scope_id)

    block.scope_type = updated_scope_type
    block.scope_id = updated_scope_id
    block.block_type = updated_block_type
    block.starts_at = updated_starts_at
    block.ends_at = updated_ends_at
    if reason_set:
        block.reason = payload.reason

    await session.commit()
    await session.refresh(block)
    return block


async def delete_block(session: AsyncSession, org_id, block_id: int) -> None:
    block = await session.get(AvailabilityBlock, block_id)
    if block is None or block.org_id != org_id:
        raise LookupError("block_not_found")
    await session.delete(block)
    await session.commit()


async def list_team_blocks(
    session: AsyncSession,
    org_id,
    team_id: int,
    *,
    starts_at: datetime,
    ends_at: datetime,
) -> list[AvailabilityBlock]:
    normalized_start = _normalize(starts_at)
    normalized_end = _normalize(ends_at)
    stmt = select(AvailabilityBlock).where(
        AvailabilityBlock.org_id == org_id,
        AvailabilityBlock.starts_at < normalized_end,
        AvailabilityBlock.ends_at > normalized_start,
        or_(
            AvailabilityBlock.scope_type == "org",
            and_(AvailabilityBlock.scope_type == "team", AvailabilityBlock.scope_id == team_id),
        ),
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_worker_blocks(
    session: AsyncSession,
    org_id,
    worker_id: int,
    *,
    starts_at: datetime,
    ends_at: datetime,
) -> list[AvailabilityBlock]:
    normalized_start = _normalize(starts_at)
    normalized_end = _normalize(ends_at)
    stmt = select(AvailabilityBlock).where(
        AvailabilityBlock.org_id == org_id,
        AvailabilityBlock.scope_type == "worker",
        AvailabilityBlock.scope_id == worker_id,
        AvailabilityBlock.starts_at < normalized_end,
        AvailabilityBlock.ends_at > normalized_start,
    )
    return list((await session.execute(stmt)).scalars().all())
