from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, require_dispatch
from app.api.org_context import require_org_context
from app.dependencies import get_db_session
from app.domain.dispatcher import schemas
from app.domain.dispatcher import service as dispatcher_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/v1/admin/dispatcher/board",
    response_model=schemas.DispatcherBoardResponse,
    status_code=status.HTTP_200_OK,
)
async def get_dispatcher_board(
    board_date: date = Query(..., alias="date", description="Target date in YYYY-MM-DD"),
    tz: str = Query("America/Edmonton", description="IANA timezone, e.g. America/Edmonton"),
    zone: str | None = Query(None, description="Optional zone filter"),
    session: AsyncSession = Depends(get_db_session),
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherBoardResponse:
    """Fetch dispatcher board bookings for a single day.

    Requires: DISPATCH permission (dispatcher/admin/owner roles).

    Returns booking timeline data, worker list, server time, and a polling-friendly
    data_version derived from the most recently updated booking in the window.
    """
    del identity
    try:
        ZoneInfo(tz)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid timezone") from exc

    result = await dispatcher_service.fetch_dispatcher_board(
        session,
        org_id=org_id,
        target_date=board_date,
        tz_name=tz,
        zone=zone,
    )

    return schemas.DispatcherBoardResponse(
        bookings=result.bookings,
        workers=result.workers,
        server_time=result.server_time,
        data_version=result.data_version,
    )
