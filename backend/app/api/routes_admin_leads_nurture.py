from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.api.admin_auth import AdminIdentity, require_any_permission_keys
from app.api.org_context import require_org_context
from app.api.problem_details import PROBLEM_TYPE_DOMAIN, problem_details
from app.dependencies import get_db_session
from app.domain.feature_modules import service as feature_service
from app.domain.leads_nurture import schemas, service

router = APIRouter(tags=["admin-leads-nurture"])


async def _require_nurture_enabled(
    request: Request,
    session: AsyncSession,
    org_id: uuid.UUID,
) -> Response | None:
    module_enabled = await feature_service.effective_feature_enabled(session, org_id, "module.leads")
    nurture_enabled = await feature_service.effective_feature_enabled(session, org_id, "leads.nurture")
    if not module_enabled or not nurture_enabled:
        return problem_details(
            request=request,
            status=status.HTTP_403_FORBIDDEN,
            title="Forbidden",
            detail="Disabled by org settings",
        )
    return None


@router.get(
    "/v1/admin/leads/nurture/campaigns",
    response_model=schemas.NurtureCampaignListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_campaigns(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.view", "leads.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.NurtureCampaignListResponse:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    campaigns = await service.list_campaigns(session, org_id)
    return schemas.NurtureCampaignListResponse(
        items=[schemas.NurtureCampaignResponse.model_validate(model) for model in campaigns]
    )


@router.post(
    "/v1/admin/leads/nurture/campaigns",
    response_model=schemas.NurtureCampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_campaign(
    request: Request,
    payload: schemas.NurtureCampaignCreateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.edit", "leads.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.NurtureCampaignResponse:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    try:
        model = await service.create_campaign(session, org_id, payload)
        await session.commit()
        await session.refresh(model)
    except IntegrityError:
        await session.rollback()
        return problem_details(
            request=request,
            status=status.HTTP_409_CONFLICT,
            title="Campaign Key Exists",
            detail="Campaign key already exists for this organization",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    return schemas.NurtureCampaignResponse.model_validate(model)


@router.get(
    "/v1/admin/leads/nurture/campaigns/{campaign_id}",
    response_model=schemas.NurtureCampaignResponse,
    status_code=status.HTTP_200_OK,
)
async def get_campaign(
    request: Request,
    campaign_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.view", "leads.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.NurtureCampaignResponse:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    model = await service.get_campaign(session, org_id, campaign_id)
    if not model:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Campaign Not Found",
            detail="Campaign does not exist",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    return schemas.NurtureCampaignResponse.model_validate(model)


@router.patch(
    "/v1/admin/leads/nurture/campaigns/{campaign_id}",
    response_model=schemas.NurtureCampaignResponse,
    status_code=status.HTTP_200_OK,
)
async def update_campaign(
    request: Request,
    campaign_id: uuid.UUID,
    payload: schemas.NurtureCampaignUpdateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.edit", "leads.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.NurtureCampaignResponse:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    try:
        model = await service.update_campaign(session, org_id, campaign_id, payload)
        if not model:
            return problem_details(
                request=request,
                status=status.HTTP_404_NOT_FOUND,
                title="Campaign Not Found",
                detail="Campaign does not exist",
                type_=PROBLEM_TYPE_DOMAIN,
            )
        await session.commit()
        await session.refresh(model)
    except IntegrityError:
        await session.rollback()
        return problem_details(
            request=request,
            status=status.HTTP_409_CONFLICT,
            title="Campaign Key Exists",
            detail="Campaign key already exists for this organization",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    return schemas.NurtureCampaignResponse.model_validate(model)


@router.delete(
    "/v1/admin/leads/nurture/campaigns/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_campaign(
    request: Request,
    campaign_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.edit", "leads.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    deleted = await service.delete_campaign(session, org_id, campaign_id)
    if not deleted:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Campaign Not Found",
            detail="Campaign does not exist",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/v1/admin/leads/nurture/campaigns/{campaign_id}/steps",
    response_model=schemas.NurtureStepListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_campaign_steps(
    request: Request,
    campaign_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.view", "leads.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.NurtureStepListResponse:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    campaign = await service.get_campaign(session, org_id, campaign_id)
    if not campaign:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Campaign Not Found",
            detail="Campaign does not exist",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    steps = await service.list_steps(session, org_id, campaign_id)
    return schemas.NurtureStepListResponse(
        items=[schemas.NurtureStepResponse.model_validate(model) for model in steps]
    )


@router.post(
    "/v1/admin/leads/nurture/campaigns/{campaign_id}/steps",
    response_model=schemas.NurtureStepResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_campaign_step(
    request: Request,
    campaign_id: uuid.UUID,
    payload: schemas.NurtureStepCreateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.edit", "leads.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.NurtureStepResponse:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    try:
        model = await service.create_step(session, org_id, campaign_id, payload)
        if not model:
            return problem_details(
                request=request,
                status=status.HTTP_404_NOT_FOUND,
                title="Campaign Not Found",
                detail="Campaign does not exist",
                type_=PROBLEM_TYPE_DOMAIN,
            )
        await session.commit()
        await session.refresh(model)
    except IntegrityError:
        await session.rollback()
        return problem_details(
            request=request,
            status=status.HTTP_409_CONFLICT,
            title="Step Conflict",
            detail="Step index already exists for this campaign",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    return schemas.NurtureStepResponse.model_validate(model)


@router.patch(
    "/v1/admin/leads/nurture/campaigns/{campaign_id}/steps/{step_id}",
    response_model=schemas.NurtureStepResponse,
    status_code=status.HTTP_200_OK,
)
async def update_campaign_step(
    request: Request,
    campaign_id: uuid.UUID,
    step_id: uuid.UUID,
    payload: schemas.NurtureStepUpdateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.edit", "leads.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.NurtureStepResponse:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    try:
        model = await service.update_step(session, org_id, campaign_id, step_id, payload)
        if not model:
            return problem_details(
                request=request,
                status=status.HTTP_404_NOT_FOUND,
                title="Step Not Found",
                detail="Step does not exist",
                type_=PROBLEM_TYPE_DOMAIN,
            )
        await session.commit()
        await session.refresh(model)
    except IntegrityError:
        await session.rollback()
        return problem_details(
            request=request,
            status=status.HTTP_409_CONFLICT,
            title="Step Conflict",
            detail="Step index already exists for this campaign",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    return schemas.NurtureStepResponse.model_validate(model)


@router.delete(
    "/v1/admin/leads/nurture/campaigns/{campaign_id}/steps/{step_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_campaign_step(
    request: Request,
    campaign_id: uuid.UUID,
    step_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.edit", "leads.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    deleted = await service.delete_step(session, org_id, campaign_id, step_id)
    if not deleted:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Step Not Found",
            detail="Step does not exist",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/v1/admin/leads/{lead_id}/nurture/enroll",
    response_model=schemas.NurtureEnrollmentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def enroll_lead(
    request: Request,
    lead_id: str,
    payload: schemas.NurtureEnrollmentCreateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.edit", "leads.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.NurtureEnrollmentCreateResponse:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    enrollment, logs, error = await service.enroll_lead(session, org_id, lead_id, payload)
    if error == "lead":
        await session.rollback()
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Lead Not Found",
            detail="Lead does not exist",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    if error == "campaign":
        await session.rollback()
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Campaign Not Found",
            detail="Campaign does not exist",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    await session.commit()
    assert enrollment is not None
    campaign = await service.get_campaign(session, org_id, enrollment.campaign_id)
    enrollment_response = schemas.NurtureEnrollmentResponse(
        enrollment_id=enrollment.enrollment_id,
        org_id=enrollment.org_id,
        lead_id=enrollment.lead_id,
        campaign_id=enrollment.campaign_id,
        campaign_key=campaign.key if campaign else None,
        campaign_name=campaign.name if campaign else None,
        enrolled_at=enrollment.enrolled_at,
        status=enrollment.status,
    )
    return schemas.NurtureEnrollmentCreateResponse(
        enrollment=enrollment_response,
        planned_logs=[
            schemas.NurtureStepLogResponse(
                log_id=log.log_id,
                org_id=log.org_id,
                enrollment_id=log.enrollment_id,
                step_index=log.step_index,
                planned_at=log.planned_at,
                sent_at=log.sent_at,
                status=log.status,
                idempotency_key=log.idempotency_key,
                error=log.error,
            )
            for log in logs
        ],
    )


@router.get(
    "/v1/admin/leads/{lead_id}/nurture/status",
    response_model=schemas.NurtureLeadStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_lead_nurture_status(
    request: Request,
    lead_id: str,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.view", "leads.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.NurtureLeadStatusResponse:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    enrollments = await service.list_enrollments_for_lead(session, org_id, lead_id)
    logs = await service.list_logs_for_enrollments(
        session, org_id, [item.enrollment_id for item in enrollments]
    )
    logs_by_enrollment: dict[uuid.UUID, list[schemas.NurtureStepLogResponse]] = {}
    for log in logs:
        logs_by_enrollment.setdefault(log.enrollment_id, []).append(
            schemas.NurtureStepLogResponse(
                log_id=log.log_id,
                org_id=log.org_id,
                enrollment_id=log.enrollment_id,
                step_index=log.step_index,
                planned_at=log.planned_at,
                sent_at=log.sent_at,
                status=log.status,
                idempotency_key=log.idempotency_key,
                error=log.error,
            )
        )
    items: list[schemas.NurtureEnrollmentStatusResponse] = []
    for enrollment in enrollments:
        campaign = await service.get_campaign(session, org_id, enrollment.campaign_id)
        items.append(
            schemas.NurtureEnrollmentStatusResponse(
                enrollment=schemas.NurtureEnrollmentResponse(
                    enrollment_id=enrollment.enrollment_id,
                    org_id=enrollment.org_id,
                    lead_id=enrollment.lead_id,
                    campaign_id=enrollment.campaign_id,
                    campaign_key=campaign.key if campaign else None,
                    campaign_name=campaign.name if campaign else None,
                    enrolled_at=enrollment.enrolled_at,
                    status=enrollment.status,
                ),
                logs=logs_by_enrollment.get(enrollment.enrollment_id, []),
            )
        )
    return schemas.NurtureLeadStatusResponse(items=items)


@router.post(
    "/v1/admin/leads/nurture/plan",
    response_model=schemas.NurturePlanResponse,
    status_code=status.HTTP_200_OK,
)
async def plan_nurture_steps(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_any_permission_keys("contacts.edit", "leads.manage")),
    session: AsyncSession = Depends(get_db_session),
    as_of: datetime | None = None,
) -> schemas.NurturePlanResponse:
    guard = await _require_nurture_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    resolved_as_of = as_of or datetime.now(timezone.utc)
    planned = await service.plan_due_steps(session, org_id, resolved_as_of)
    items: list[schemas.NurturePlanStepResponse] = []
    for log, enrollment, campaign, step in planned:
        items.append(
            schemas.NurturePlanStepResponse(
                log_id=log.log_id,
                enrollment_id=enrollment.enrollment_id,
                lead_id=enrollment.lead_id,
                campaign_id=campaign.campaign_id,
                campaign_key=campaign.key,
                step_index=log.step_index,
                planned_at=log.planned_at,
                channel=step.channel,
                template_key=step.template_key,
                payload_json=step.payload_json,
                status=log.status,
                idempotency_key=log.idempotency_key,
            )
        )
    return schemas.NurturePlanResponse(as_of=resolved_as_of, items=items)
