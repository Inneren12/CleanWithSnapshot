from __future__ import annotations

from datetime import date, timedelta
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, require_permission_keys
from app.api.org_context import require_org_context
from app.domain.analytics import competitors_service, schemas
from app.domain.feature_modules import service as feature_service
from app.infra.db import get_db_session

router = APIRouter(tags=["admin-analytics"])


async def _require_competitors_enabled(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    module_enabled = await feature_service.effective_feature_enabled(session, org_id, "module.analytics")
    competitors_enabled = await feature_service.effective_feature_enabled(
        session, org_id, "analytics.competitors"
    )
    if not module_enabled or not competitors_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Competitor analytics disabled")


def _resolve_range(value_from: date | None, value_to: date | None) -> tuple[date, date]:
    today = date.today()
    range_end = value_to or today
    range_start = value_from or (range_end - timedelta(days=30))
    if range_start > range_end:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date range")
    return range_start, range_end


@router.get(
    "/v1/admin/analytics/competitors/benchmark",
    response_model=schemas.CompetitorBenchmarkResponse,
    status_code=status.HTTP_200_OK,
)
async def get_competitor_benchmark(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.CompetitorBenchmarkResponse:
    await _require_competitors_enabled(session, org_id)
    range_start, range_end = _resolve_range(from_date, to_date)
    items = await competitors_service.benchmark_competitors(session, org_id, range_start, range_end)
    return schemas.CompetitorBenchmarkResponse(
        range_start=range_start,
        range_end=range_end,
        items=items,
    )


@router.get(
    "/v1/admin/analytics/competitors",
    response_model=list[schemas.CompetitorResponse],
    status_code=status.HTTP_200_OK,
)
async def list_competitors(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
    session: AsyncSession = Depends(get_db_session),
) -> list[schemas.CompetitorResponse]:
    await _require_competitors_enabled(session, org_id)
    return await competitors_service.list_competitors(session, org_id)


@router.post(
    "/v1/admin/analytics/competitors",
    response_model=schemas.CompetitorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_competitor(
    payload: schemas.CompetitorCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.CompetitorResponse:
    await _require_competitors_enabled(session, org_id)
    competitor = await competitors_service.create_competitor(session, org_id, payload)
    await session.commit()
    return competitor


@router.get(
    "/v1/admin/analytics/competitors/{competitor_id}",
    response_model=schemas.CompetitorResponse,
    status_code=status.HTTP_200_OK,
)
async def get_competitor(
    competitor_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.CompetitorResponse:
    await _require_competitors_enabled(session, org_id)
    competitor = await competitors_service.get_competitor(session, org_id, competitor_id)
    if competitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competitor not found")
    return schemas.CompetitorResponse(
        competitor_id=competitor.competitor_id,
        name=competitor.name,
        platform=competitor.platform,
        profile_url=competitor.profile_url,
        created_at=competitor.created_at,
    )


@router.patch(
    "/v1/admin/analytics/competitors/{competitor_id}",
    response_model=schemas.CompetitorResponse,
    status_code=status.HTTP_200_OK,
)
async def update_competitor(
    competitor_id: uuid.UUID,
    payload: schemas.CompetitorUpdate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.CompetitorResponse:
    await _require_competitors_enabled(session, org_id)
    competitor = await competitors_service.update_competitor(session, org_id, competitor_id, payload)
    if competitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competitor not found")
    await session.commit()
    return competitor


@router.delete(
    "/v1/admin/analytics/competitors/{competitor_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_competitor(
    competitor_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await _require_competitors_enabled(session, org_id)
    deleted = await competitors_service.delete_competitor(session, org_id, competitor_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competitor not found")
    await session.commit()


@router.get(
    "/v1/admin/analytics/competitors/{competitor_id}/metrics",
    response_model=list[schemas.CompetitorMetricResponse],
    status_code=status.HTTP_200_OK,
)
async def list_competitor_metrics(
    competitor_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
    session: AsyncSession = Depends(get_db_session),
) -> list[schemas.CompetitorMetricResponse]:
    await _require_competitors_enabled(session, org_id)
    competitor = await competitors_service.get_competitor(session, org_id, competitor_id)
    if competitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competitor not found")
    return await competitors_service.list_metrics(session, org_id, competitor_id)


@router.post(
    "/v1/admin/analytics/competitors/{competitor_id}/metrics",
    response_model=schemas.CompetitorMetricResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_competitor_metric(
    competitor_id: uuid.UUID,
    payload: schemas.CompetitorMetricCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.CompetitorMetricResponse:
    await _require_competitors_enabled(session, org_id)
    metric = await competitors_service.create_metric(session, org_id, competitor_id, payload)
    if metric is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competitor not found")
    await session.commit()
    return metric


@router.patch(
    "/v1/admin/analytics/competitors/{competitor_id}/metrics/{metric_id}",
    response_model=schemas.CompetitorMetricResponse,
    status_code=status.HTTP_200_OK,
)
async def update_competitor_metric(
    competitor_id: uuid.UUID,
    metric_id: uuid.UUID,
    payload: schemas.CompetitorMetricUpdate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.CompetitorMetricResponse:
    await _require_competitors_enabled(session, org_id)
    metric = await competitors_service.update_metric(
        session, org_id, competitor_id, metric_id, payload
    )
    if metric is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found")
    await session.commit()
    return metric


@router.delete(
    "/v1/admin/analytics/competitors/{competitor_id}/metrics/{metric_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_competitor_metric(
    competitor_id: uuid.UUID,
    metric_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await _require_competitors_enabled(session, org_id)
    deleted = await competitors_service.delete_metric(session, org_id, competitor_id, metric_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found")
    await session.commit()
