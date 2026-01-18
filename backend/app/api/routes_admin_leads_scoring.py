from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.api.admin_auth import AdminIdentity, require_permission_keys
from app.api.org_context import require_org_context
from app.api.problem_details import PROBLEM_TYPE_DOMAIN, problem_details
from app.dependencies import get_db_session
from app.domain.feature_modules import service as feature_service
from app.domain.leads_scoring import schemas, service

router = APIRouter(tags=["admin-leads-scoring"])


async def _require_scoring_enabled(
    request: Request,
    session: AsyncSession,
    org_id: uuid.UUID,
) -> Response | None:
    module_enabled = await feature_service.effective_feature_enabled(session, org_id, "module.leads")
    scoring_enabled = await feature_service.effective_feature_enabled(session, org_id, "leads.scoring")
    if not module_enabled or not scoring_enabled:
        return problem_details(
            request=request,
            status=status.HTTP_403_FORBIDDEN,
            title="Forbidden",
            detail="Disabled by org settings",
        )
    return None


@router.get(
    "/v1/admin/leads/scoring/rules",
    response_model=schemas.LeadScoringRulesListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_rules(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("leads.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.LeadScoringRulesListResponse:
    guard = await _require_scoring_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    rules = await service.list_rules(session, org_id)
    active = next((rule for rule in rules if rule.enabled), None)
    return schemas.LeadScoringRulesListResponse(
        active_version=active.version if active else None,
        items=[
            schemas.LeadScoringRuleVersionResponse(
                org_id=rule.org_id,
                version=rule.version,
                enabled=rule.enabled,
                rules=[
                    schemas.LeadScoringRuleDefinition.model_validate(definition)
                    for definition in (rule.rules_json or [])
                ],
                created_at=rule.created_at,
            )
            for rule in rules
        ],
    )


@router.patch(
    "/v1/admin/leads/scoring/rules",
    response_model=schemas.LeadScoringRuleVersionResponse,
    status_code=status.HTTP_200_OK,
)
async def update_rules(
    request: Request,
    payload: schemas.LeadScoringRulesUpdateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("leads.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.LeadScoringRuleVersionResponse:
    guard = await _require_scoring_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    model = await service.create_rules_version(session, org_id, payload)
    await session.commit()
    await session.refresh(model)
    return schemas.LeadScoringRuleVersionResponse(
        org_id=model.org_id,
        version=model.version,
        enabled=model.enabled,
        rules=[
            schemas.LeadScoringRuleDefinition.model_validate(definition)
            for definition in (model.rules_json or [])
        ],
        created_at=model.created_at,
    )


@router.post(
    "/v1/admin/leads/{lead_id}/scoring/recompute",
    response_model=schemas.LeadScoringSnapshotResponse,
    status_code=status.HTTP_200_OK,
)
async def recompute_lead_score(
    request: Request,
    lead_id: str,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("leads.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.LeadScoringSnapshotResponse:
    guard = await _require_scoring_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    lead = await service.get_lead(session, org_id, lead_id)
    if lead is None:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Lead Not Found",
            detail="Lead does not exist",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    rules = await service.get_active_rules(session, org_id)
    if rules is None:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Scoring Rules Not Found",
            detail="Scoring rules are not configured",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    snapshot = await service.recompute_score(session, org_id, lead, rules)
    await session.commit()
    await session.refresh(snapshot)
    return schemas.LeadScoringSnapshotResponse(
        org_id=snapshot.org_id,
        lead_id=snapshot.lead_id,
        score=snapshot.score,
        reasons=[
            schemas.LeadScoringReason(
                rule_key=reason.get("rule_key", ""),
                label=reason.get("label", ""),
                points=reason.get("points", 0),
            )
            for reason in (snapshot.reasons_json or [])
        ],
        computed_at=snapshot.computed_at,
        rules_version=snapshot.rules_version,
    )


@router.get(
    "/v1/admin/leads/{lead_id}/scoring",
    response_model=schemas.LeadScoringSnapshotResponse,
    status_code=status.HTTP_200_OK,
)
async def get_lead_score(
    request: Request,
    lead_id: str,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("leads.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.LeadScoringSnapshotResponse:
    guard = await _require_scoring_enabled(request, session, org_id)
    if isinstance(guard, Response):
        return guard
    snapshot = await service.get_snapshot(session, org_id, lead_id)
    if snapshot is None:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Lead Score Not Found",
            detail="No score snapshot exists for this lead",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    return schemas.LeadScoringSnapshotResponse(
        org_id=snapshot.org_id,
        lead_id=snapshot.lead_id,
        score=snapshot.score,
        reasons=[
            schemas.LeadScoringReason(
                rule_key=reason.get("rule_key", ""),
                label=reason.get("label", ""),
                points=reason.get("points", 0),
            )
            for reason in (snapshot.reasons_json or [])
        ],
        computed_at=snapshot.computed_at,
        rules_version=snapshot.rules_version,
    )
