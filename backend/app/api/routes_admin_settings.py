from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, AdminPermission, AdminRole, require_permissions, require_viewer
from app.api.org_context import require_org_context
from app.domain.feature_modules import schemas as feature_schemas
from app.domain.feature_modules import service as feature_service
from app.infra.db import get_db_session

router = APIRouter(tags=["admin-settings"])


async def require_owner(
    identity: AdminIdentity = Depends(require_permissions(AdminPermission.ADMIN)),
) -> AdminIdentity:
    if identity.role != AdminRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


def _resolve_user_key(request: Request, identity: AdminIdentity) -> str:
    saas_identity = getattr(request.state, "saas_identity", None)
    if saas_identity and getattr(saas_identity, "user_id", None):
        return f"saas:{saas_identity.user_id}"
    return f"basic:{identity.username}"


@router.get(
    "/v1/admin/settings/features",
    response_model=feature_schemas.FeatureConfigResponse,
    status_code=status.HTTP_200_OK,
)
async def get_feature_config(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> feature_schemas.FeatureConfigResponse:
    overrides = await feature_service.get_org_feature_overrides(session, org_id)
    defaults = feature_service.default_feature_map()
    effective = feature_service.resolve_effective_features(overrides)
    return feature_schemas.FeatureConfigResponse(
        org_id=org_id,
        overrides=overrides,
        defaults=defaults,
        effective=effective,
        keys=feature_service.FEATURE_KEYS,
    )


@router.patch(
    "/v1/admin/settings/features",
    response_model=feature_schemas.FeatureConfigResponse,
    status_code=status.HTTP_200_OK,
)
async def update_feature_config(
    payload: feature_schemas.FeatureConfigUpdateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> feature_schemas.FeatureConfigResponse:
    overrides = feature_service.normalize_feature_overrides(payload.overrides)
    await feature_service.upsert_org_feature_overrides(session, org_id, overrides)
    await session.commit()
    defaults = feature_service.default_feature_map()
    effective = feature_service.resolve_effective_features(overrides)
    return feature_schemas.FeatureConfigResponse(
        org_id=org_id,
        overrides=overrides,
        defaults=defaults,
        effective=effective,
        keys=feature_service.FEATURE_KEYS,
    )


@router.get(
    "/v1/admin/users/me/ui_prefs",
    response_model=feature_schemas.UiPrefsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_ui_prefs(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> feature_schemas.UiPrefsResponse:
    user_key = _resolve_user_key(request, identity)
    hidden_keys = await feature_service.get_user_ui_prefs(session, org_id, user_key)
    return feature_schemas.UiPrefsResponse(hidden_keys=hidden_keys)


@router.patch(
    "/v1/admin/users/me/ui_prefs",
    response_model=feature_schemas.UiPrefsResponse,
    status_code=status.HTTP_200_OK,
)
async def update_ui_prefs(
    payload: feature_schemas.UiPrefsUpdateRequest,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> feature_schemas.UiPrefsResponse:
    user_key = _resolve_user_key(request, identity)
    hidden_keys = feature_service.normalize_hidden_keys(payload.hidden_keys)
    await feature_service.upsert_user_ui_prefs(session, org_id, user_key, hidden_keys)
    await session.commit()
    return feature_schemas.UiPrefsResponse(hidden_keys=hidden_keys)
