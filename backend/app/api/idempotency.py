from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
import uuid

from fastapi import Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.problem_details import (
    PROBLEM_TYPE_DOMAIN,
    PROBLEM_TYPE_RATE_LIMIT,
    PROBLEM_TYPE_VALIDATION,
    problem_details,
)
from app.domain.admin_idempotency import AdminIdempotency
from app.domain.admin_audit import service as admin_audit_service
from app.infra.security import RateLimiter
from app.infra.metrics import metrics
from app.settings import settings

IDEMPOTENCY_PENDING_STATUS = AdminIdempotency.STATUS_PENDING
IDEMPOTENCY_FAILURE_STATUS = status.HTTP_500_INTERNAL_SERVER_ERROR


def _build_response(record: AdminIdempotency) -> Response:
    if record.response_status == IDEMPOTENCY_PENDING_STATUS:
        response: Response = Response(status_code=status.HTTP_409_CONFLICT)
        response.headers["Retry-After"] = "1"
    elif record.response_status <= 0:
        response_status = IDEMPOTENCY_FAILURE_STATUS
        if record.response_body_json is None:
            response = Response(status_code=response_status)
        else:
            response = JSONResponse(content=record.response_body_json, status_code=response_status)
    elif record.response_body_json is None:
        response = Response(status_code=record.response_status)
    else:
        response = JSONResponse(content=record.response_body_json, status_code=record.response_status)
    response.headers["Idempotency-Key"] = record.key
    return response


async def _normalized_body(request: Request) -> str:
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        raw_body = await request.body()
        return raw_body.decode() if raw_body else ""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _request_fingerprint(request: Request, body: str) -> str:
    payload = f"{request.method}:{request.url.path}:{body}".encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass
class IdempotencyContext:
    key: str
    org_id: uuid.UUID
    endpoint_id: str
    request_hash: str
    claimed_record: AdminIdempotency
    existing_response: Response | None = None

    async def save_response(
        self, session: AsyncSession, *, status_code: int, body: dict | list | None
    ) -> None:
        if self.existing_response is not None:
            return

        self.claimed_record.response_status = status_code
        self.claimed_record.response_body_json = body if isinstance(body, (dict, list)) else None
        await session.flush()

    async def mark_failed(self, session: AsyncSession) -> None:
        if self.existing_response is not None:
            return
        self.claimed_record.response_status = IDEMPOTENCY_FAILURE_STATUS
        self.claimed_record.response_body_json = {
            "detail": "Request processing failed",
            "status": IDEMPOTENCY_FAILURE_STATUS,
            "title": "Internal Server Error",
        }
        await session.flush()


async def require_idempotency(
    request: Request, session: AsyncSession, org_id: uuid.UUID, endpoint_id: str
) -> IdempotencyContext | Response:
    key = request.headers.get("Idempotency-Key")
    if not key:
        return problem_details(
            request=request,
            status=status.HTTP_400_BAD_REQUEST,
            title="Idempotency key required",
            detail="Idempotency-Key header is required for this endpoint",
            type_=PROBLEM_TYPE_VALIDATION,
        )

    normalized_body = await _normalized_body(request)
    fingerprint = _request_fingerprint(request, normalized_body)

    insert_values = dict(
        org_id=org_id,
        key=key,
        endpoint=endpoint_id,
        request_hash=fingerprint,
        response_status=IDEMPOTENCY_PENDING_STATUS,
        response_body_json=None,
    )
    bind = session.get_bind()
    dialect_name = bind.dialect.name
    if dialect_name == "postgresql":
        claim_stmt = pg_insert(AdminIdempotency).values(**insert_values).on_conflict_do_nothing(
            index_elements=["org_id", "key", "endpoint"]
        )
    else:
        claim_stmt = sqlite_insert(AdminIdempotency).values(**insert_values).on_conflict_do_nothing(
            index_elements=["org_id", "key", "endpoint"]
        )
    claim_result = await session.execute(claim_stmt)
    claimed = claim_result.rowcount == 1

    stmt = select(AdminIdempotency).where(
        AdminIdempotency.org_id == org_id,
        AdminIdempotency.key == key,
        AdminIdempotency.endpoint == endpoint_id,
    )
    result = await session.execute(stmt)
    record = result.scalar_one()

    if record.request_hash != fingerprint:
        return problem_details(
            request=request,
            status=status.HTTP_409_CONFLICT,
            title="Idempotency conflict",
            detail="Idempotency-Key has already been used with a different payload",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    if claimed:
        return IdempotencyContext(
            key=key,
            org_id=org_id,
            endpoint_id=endpoint_id,
            request_hash=fingerprint,
            claimed_record=record,
        )

    return _build_response(record)


async def enforce_org_action_rate_limit(
    request: Request, org_id: uuid.UUID, action: str, limiter: RateLimiter | None = None
) -> Response | None:
    limiter = limiter or _resolve_rate_limiter(request)
    if limiter is None:
        return None

    key = f"org:{org_id}:action:{action}"
    allowed = await limiter.allow(key)
    if allowed:
        return None

    request_id = getattr(request.state, "request_id", None)
    metrics.record_rate_limit_block("admin_action")
    metrics.record_http_429("admin_action")
    logger = logging.getLogger(__name__)
    logger.warning(
        "org_action_rate_limited",
        extra={
            "extra": {
                "org_id": str(org_id),
                "request_id": str(request_id) if request_id else None,
                "action": action,
                "limit_per_minute": settings.admin_action_rate_limit_per_minute,
            }
        },
    )
    identity = getattr(request.state, "admin_identity", None)
    if identity:
        session_factory = getattr(request.app.state, "db_session_factory", None)
        if session_factory:
            async with session_factory() as session:
                await admin_audit_service.record_action(
                    session,
                    identity=identity,
                    org_id=org_id,
                    action="org_action_rate_limit_rejected",
                    resource_type="admin_action",
                    resource_id=action,
                    before=None,
                    after={
                        "action": action,
                        "request_id": str(request_id) if request_id else None,
                        "limit_per_minute": settings.admin_action_rate_limit_per_minute,
                    },
                )
                await session.commit()

    return problem_details(
        request=request,
        status=status.HTTP_429_TOO_MANY_REQUESTS,
        title="Too Many Requests",
        detail="Rate limit exceeded for this action",
        type_=PROBLEM_TYPE_RATE_LIMIT,
    )


def _resolve_rate_limiter(request: Request) -> RateLimiter | None:
    limiter = getattr(request.app.state, "action_rate_limiter", None)
    if limiter:
        return limiter
    services = getattr(request.app.state, "services", None)
    return getattr(services, "action_rate_limiter", None) or getattr(request.app.state, "rate_limiter", None)
