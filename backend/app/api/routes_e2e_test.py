"""
E2E Test Hooks - endpoints only available in test environments.

These endpoints are gated by APP_ENV and must not be available in production.
They provide deterministic control for E2E tests.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import entitlements
from app.api.admin_auth import AdminIdentity, require_admin
from app.domain.data_rights import service as data_rights_service
from app.domain.leads.db_models import Lead
from app.infra.db import get_db_session
from app.infra.storage import new_storage_backend
from app.settings import settings

router = APIRouter(tags=["e2e-test"], prefix="/v1/admin/test")
logger = logging.getLogger(__name__)

_ALLOWED_ENVS = {"ci", "e2e", "test", "dev", "local"}


def _require_test_env() -> None:
    """Ensure we're in a test environment."""
    if settings.app_env not in _ALLOWED_ENVS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )


class SeedLeadRequest(BaseModel):
    name: str = "E2E Test Lead"
    email: EmailStr | None = None
    phone: str = "+15555550199"


class SeedLeadResponse(BaseModel):
    lead_id: str
    email: str | None
    name: str


class ProcessDataExportsResponse(BaseModel):
    processed: int
    completed: int
    failed: int


@router.post("/seed-lead", response_model=SeedLeadResponse)
async def seed_test_lead(
    request: Request,
    payload: SeedLeadRequest,
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_admin),
) -> SeedLeadResponse:
    """
    Seed a minimal lead for E2E testing.
    Only available in test environments (ci, e2e, test, dev, local).
    """
    _require_test_env()

    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)

    # Generate unique email if not provided
    email = payload.email or f"e2e-{uuid.uuid4().hex[:8]}@test.invalid"

    lead = Lead(
        org_id=org_id,
        name=payload.name,
        phone=payload.phone,
        email=email,
        preferred_dates=[],
        structured_inputs={"beds": 1, "baths": 1},
        estimate_snapshot={"total": 10000},
        pricing_config_version="e2e-test",
        config_hash="e2e-hash",
        status="NEW",
        source="e2e_test",
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    logger.info(
        "Seeded E2E test lead",
        extra={"lead_id": lead.lead_id, "email": email, "org_id": str(org_id)},
    )

    return SeedLeadResponse(
        lead_id=lead.lead_id,
        email=lead.email,
        name=lead.name,
    )


@router.post("/process-data-exports", response_model=ProcessDataExportsResponse)
async def process_data_exports(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_admin),
) -> ProcessDataExportsResponse:
    """
    Process pending data export requests immediately.
    Only available in test environments (ci, e2e, test, dev, local).

    This provides deterministic E2E testing without relying on background job timing.
    """
    _require_test_env()

    # Import here to avoid circular imports
    from app.jobs.data_export import run_pending_data_exports

    storage = getattr(request.app.state, "storage_backend", None) or new_storage_backend()
    result = await run_pending_data_exports(session, storage_backend=storage)

    logger.info(
        "Processed data exports for E2E test",
        extra={"processed": result.get("processed", 0), "completed": result.get("completed", 0)},
    )

    return ProcessDataExportsResponse(
        processed=result.get("processed", 0),
        completed=result.get("completed", 0),
        failed=result.get("failed", 0),
    )


@router.post("/process-deletions")
async def process_deletions(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_admin),
) -> dict[str, int]:
    """
    Process pending data deletion requests immediately.
    Only available in test environments (ci, e2e, test, dev, local).

    This provides deterministic E2E testing without relying on background job timing.
    """
    _require_test_env()

    storage = getattr(request.app.state, "storage_backend", None) or new_storage_backend()
    result = await data_rights_service.process_pending_deletions(
        session, storage_backend=storage
    )

    logger.info(
        "Processed deletions for E2E test",
        extra={"processed": result.get("processed", 0), "leads_anonymized": result.get("leads_anonymized", 0)},
    )

    return result
