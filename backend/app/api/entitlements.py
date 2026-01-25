from __future__ import annotations

import logging
import uuid
from typing import Callable, Tuple

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import saas_auth
from app.api.saas_auth import _get_saas_token
from app.api.admin_auth import AdminIdentity, AdminRole
from app.domain.admin_audit import service as admin_audit_service
from app.domain.saas import billing_service
from app.domain.saas.plans import Plan, get_plan
from app.infra.db import get_db_session
from app.infra.org_context import set_current_org_id
from app.infra.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)


def _resolve_request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return str(request_id)
    return request.headers.get("X-Request-ID")


def _system_identity(org_id: uuid.UUID) -> AdminIdentity:
    return AdminIdentity(
        username="system",
        role=AdminRole.ADMIN,
        org_id=org_id,
        admin_id="system",
        auth_method="system",
    )


def resolve_org_id(request: Request) -> uuid.UUID:
    error: HTTPException | None = getattr(request.state, "saas_identity_error", None)
    if error:
        raise error

    org_id = getattr(request.state, "current_org_id", None)
    if org_id is not None:
        resolved = uuid.UUID(str(org_id))
        set_current_org_id(resolved)
        return resolved

    header_value = request.headers.get("X-Test-Org")
    allow_test_header = settings.testing or settings.app_env == "dev"
    if allow_test_header and header_value:
        try:
            org_uuid = uuid.UUID(header_value)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Test-Org header",
            ) from exc
        request.state.current_org_id = org_uuid
        set_current_org_id(org_uuid)
        return org_uuid
    if header_value and not allow_test_header:
        logger = logging.getLogger(__name__)
        logger.debug("ignored_test_org_header", extra={"extra": {"reason": "disabled"}})
    set_current_org_id(settings.default_org_id)
    request.state.current_org_id = settings.default_org_id
    return settings.default_org_id


def _has_tenant_identity(request: Request) -> bool:
    if getattr(request.state, "saas_identity", None) is not None:
        return True
    return _get_saas_token(request) is not None


def has_tenant_identity(request: Request) -> bool:
    return _has_tenant_identity(request)


async def _ensure_saas_identity_if_token_present(request: Request) -> None:
    if getattr(request.state, "saas_identity", None) is not None:
        return
    token = _get_saas_token(request)
    if not token:
        return
    identity = await saas_auth._load_identity(request, token, strict=True)
    request.state.saas_identity = identity
    request.state.current_org_id = identity.org_id
    set_current_org_id(identity.org_id)


async def _plan_and_usage(session: AsyncSession, org_id: uuid.UUID) -> Tuple[Plan, dict[str, int]]:
    plan = await billing_service.get_current_plan(session, org_id)
    usage = await billing_service.usage_snapshot(session, org_id)
    return plan, usage


async def require_worker_entitlement(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> Plan:
    await _ensure_saas_identity_if_token_present(request)
    if not _has_tenant_identity(request):
        return get_plan(None)
    org_id = resolve_org_id(request)
    plan, usage = await _plan_and_usage(session, org_id)
    if usage["workers"] >= plan.limits.max_workers:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Worker limit reached for current plan",
        )
    return plan


async def require_booking_entitlement(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> Plan:
    await _ensure_saas_identity_if_token_present(request)
    if not _has_tenant_identity(request):
        return get_plan(None)
    org_id = getattr(request.state, "current_org_id", None) or settings.default_org_id
    plan, usage = await _plan_and_usage(session, org_id)
    if usage["bookings_this_month"] >= plan.limits.max_bookings_per_month:
        request_id = _resolve_request_id(request)
        logger.warning(
            "org_booking_quota_rejected",
            extra={
                "extra": {
                    "org_id": str(org_id),
                    "request_id": request_id,
                    "quota_type": "bookings_per_month",
                    "bookings_this_month": usage["bookings_this_month"],
                    "max_bookings_per_month": plan.limits.max_bookings_per_month,
                }
            },
        )
        await admin_audit_service.record_action(
            session,
            identity=_system_identity(org_id),
            org_id=org_id,
            action="org_booking_quota_rejected",
            resource_type="org_booking_quota",
            resource_id=str(org_id),
            before=None,
            after={
                "bookings_this_month": usage["bookings_this_month"],
                "max_bookings_per_month": plan.limits.max_bookings_per_month,
                "request_id": request_id,
            },
        )
        metrics.record_org_active_bookings_quota_rejection("monthly_limit")
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Monthly booking limit reached for current plan",
        )
    return plan


async def enforce_storage_entitlement(
    request: Request,
    bytes_to_add: int,
    session: AsyncSession = Depends(get_db_session),
) -> Plan:
    await _ensure_saas_identity_if_token_present(request)
    if not _has_tenant_identity(request):
        return get_plan(None)
    org_id = resolve_org_id(request)
    plan, usage = await _plan_and_usage(session, org_id)
    limit_bytes = plan.limits.storage_gb * 1024 * 1024 * 1024
    if usage["storage_bytes"] + bytes_to_add > limit_bytes:
        request_id = _resolve_request_id(request)
        logger.warning(
            "org_storage_quota_rejected",
            extra={
                "extra": {
                    "org_id": str(org_id),
                    "request_id": request_id,
                    "quota_type": "plan_storage_gb",
                    "bytes_requested": bytes_to_add,
                    "storage_bytes_used": usage["storage_bytes"],
                    "max_storage_bytes": limit_bytes,
                }
            },
        )
        await admin_audit_service.record_action(
            session,
            identity=_system_identity(org_id),
            org_id=org_id,
            action="org_storage_plan_quota_rejected",
            resource_type="org_storage_quota",
            resource_id=str(org_id),
            before=None,
            after={
                "bytes_requested": bytes_to_add,
                "storage_bytes_used": usage["storage_bytes"],
                "max_storage_bytes": limit_bytes,
                "request_id": request_id,
            },
        )
        metrics.record_org_storage_quota_rejection("plan_limit")
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Storage limit reached for current plan",
        )
    return plan


def record_usage(metric: str, quantity_getter: Callable[[Request], int], resource_id_getter: Callable[[Request], str | None] | None = None):
    async def _record(
        request: Request,
        session: AsyncSession = Depends(get_db_session),
    ) -> None:
        if not _has_tenant_identity(request):
            return
        org_id = resolve_org_id(request)
        quantity = quantity_getter(request)
        resource_id = resource_id_getter(request) if resource_id_getter else None
        await billing_service.record_usage_event(
            session,
            org_id,
            metric=metric,
            quantity=quantity,
            resource_id=resource_id,
        )

    return _record
