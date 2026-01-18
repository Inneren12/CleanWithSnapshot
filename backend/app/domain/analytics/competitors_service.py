from __future__ import annotations

from datetime import date
import uuid

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.analytics import schemas
from app.domain.analytics.db_models import Competitor, CompetitorMetric


def _serialize_competitor(competitor: Competitor) -> schemas.CompetitorResponse:
    return schemas.CompetitorResponse(
        competitor_id=competitor.competitor_id,
        name=competitor.name,
        platform=competitor.platform,
        profile_url=competitor.profile_url,
        created_at=competitor.created_at,
    )


def _serialize_metric(metric: CompetitorMetric) -> schemas.CompetitorMetricResponse:
    return schemas.CompetitorMetricResponse(
        metric_id=metric.metric_id,
        competitor_id=metric.competitor_id,
        as_of_date=metric.as_of_date,
        rating=metric.rating,
        review_count=metric.review_count,
        avg_response_hours=metric.avg_response_hours,
        created_at=metric.created_at,
    )


async def list_competitors(
    session: AsyncSession, org_id: uuid.UUID
) -> list[schemas.CompetitorResponse]:
    stmt = select(Competitor).where(Competitor.org_id == org_id).order_by(Competitor.created_at.desc())
    result = await session.execute(stmt)
    return [_serialize_competitor(row) for row in result.scalars().all()]


async def get_competitor(
    session: AsyncSession, org_id: uuid.UUID, competitor_id: uuid.UUID
) -> Competitor | None:
    stmt = select(Competitor).where(
        Competitor.competitor_id == competitor_id,
        Competitor.org_id == org_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_competitor(
    session: AsyncSession, org_id: uuid.UUID, payload: schemas.CompetitorCreate
) -> schemas.CompetitorResponse:
    competitor = Competitor(org_id=org_id, **payload.model_dump())
    session.add(competitor)
    await session.flush()
    return _serialize_competitor(competitor)


async def update_competitor(
    session: AsyncSession,
    org_id: uuid.UUID,
    competitor_id: uuid.UUID,
    payload: schemas.CompetitorUpdate,
) -> schemas.CompetitorResponse | None:
    competitor = await get_competitor(session, org_id, competitor_id)
    if competitor is None:
        return None
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(competitor, key, value)
    await session.flush()
    return _serialize_competitor(competitor)


async def delete_competitor(
    session: AsyncSession, org_id: uuid.UUID, competitor_id: uuid.UUID
) -> bool:
    competitor = await get_competitor(session, org_id, competitor_id)
    if competitor is None:
        return False
    await session.delete(competitor)
    return True


async def list_metrics(
    session: AsyncSession, org_id: uuid.UUID, competitor_id: uuid.UUID
) -> list[schemas.CompetitorMetricResponse]:
    stmt = (
        select(CompetitorMetric)
        .join(Competitor, CompetitorMetric.competitor_id == Competitor.competitor_id)
        .where(
            CompetitorMetric.competitor_id == competitor_id,
            Competitor.org_id == org_id,
        )
        .order_by(CompetitorMetric.as_of_date.desc())
    )
    result = await session.execute(stmt)
    return [_serialize_metric(row) for row in result.scalars().all()]


async def create_metric(
    session: AsyncSession,
    org_id: uuid.UUID,
    competitor_id: uuid.UUID,
    payload: schemas.CompetitorMetricCreate,
) -> schemas.CompetitorMetricResponse | None:
    competitor = await get_competitor(session, org_id, competitor_id)
    if competitor is None:
        return None
    metric = CompetitorMetric(competitor_id=competitor_id, **payload.model_dump())
    session.add(metric)
    await session.flush()
    return _serialize_metric(metric)


async def update_metric(
    session: AsyncSession,
    org_id: uuid.UUID,
    competitor_id: uuid.UUID,
    metric_id: uuid.UUID,
    payload: schemas.CompetitorMetricUpdate,
) -> schemas.CompetitorMetricResponse | None:
    stmt = (
        select(CompetitorMetric)
        .join(Competitor, CompetitorMetric.competitor_id == Competitor.competitor_id)
        .where(
            CompetitorMetric.metric_id == metric_id,
            CompetitorMetric.competitor_id == competitor_id,
            Competitor.org_id == org_id,
        )
    )
    result = await session.execute(stmt)
    metric = result.scalar_one_or_none()
    if metric is None:
        return None
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(metric, key, value)
    await session.flush()
    return _serialize_metric(metric)


async def delete_metric(
    session: AsyncSession,
    org_id: uuid.UUID,
    competitor_id: uuid.UUID,
    metric_id: uuid.UUID,
) -> bool:
    stmt = (
        select(CompetitorMetric)
        .join(Competitor, CompetitorMetric.competitor_id == Competitor.competitor_id)
        .where(
            CompetitorMetric.metric_id == metric_id,
            CompetitorMetric.competitor_id == competitor_id,
            Competitor.org_id == org_id,
        )
    )
    result = await session.execute(stmt)
    metric = result.scalar_one_or_none()
    if metric is None:
        return False
    await session.delete(metric)
    return True


async def benchmark_competitors(
    session: AsyncSession,
    org_id: uuid.UUID,
    range_start: date,
    range_end: date,
) -> list[schemas.CompetitorBenchmarkEntry]:
    join_condition = sa.and_(
        CompetitorMetric.competitor_id == Competitor.competitor_id,
        CompetitorMetric.as_of_date >= range_start,
        CompetitorMetric.as_of_date <= range_end,
    )
    stmt = (
        select(
            Competitor.competitor_id,
            Competitor.name,
            Competitor.platform,
            Competitor.profile_url,
            sa.func.count(CompetitorMetric.metric_id).label("sample_count"),
            sa.func.avg(CompetitorMetric.rating).label("avg_rating"),
            sa.func.max(CompetitorMetric.review_count).label("max_review_count"),
            sa.func.avg(CompetitorMetric.avg_response_hours).label("avg_response_hours"),
            sa.func.max(CompetitorMetric.as_of_date).label("latest_metric_date"),
        )
        .select_from(Competitor)
        .outerjoin(CompetitorMetric, join_condition)
        .where(Competitor.org_id == org_id)
        .group_by(
            Competitor.competitor_id,
            Competitor.name,
            Competitor.platform,
            Competitor.profile_url,
        )
        .order_by(Competitor.name.asc())
    )
    result = await session.execute(stmt)
    entries: list[schemas.CompetitorBenchmarkEntry] = []
    for row in result.all():
        (
            competitor_id,
            name,
            platform,
            profile_url,
            sample_count,
            avg_rating,
            max_review_count,
            avg_response_hours,
            latest_metric_date,
        ) = row
        entries.append(
            schemas.CompetitorBenchmarkEntry(
                competitor_id=competitor_id,
                name=name,
                platform=platform,
                profile_url=profile_url,
                sample_count=int(sample_count or 0),
                avg_rating=float(avg_rating) if avg_rating is not None else None,
                max_review_count=int(max_review_count) if max_review_count is not None else None,
                avg_response_hours=(
                    float(avg_response_hours) if avg_response_hours is not None else None
                ),
                latest_metric_date=latest_metric_date,
            )
        )
    return entries
