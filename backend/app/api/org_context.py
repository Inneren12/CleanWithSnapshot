import uuid
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status

from app.api.entitlements import resolve_org_id
from app.api.saas_auth import SaaSIdentity, _get_cached_identity, _get_saas_token
from app.infra.org_context import set_current_org_id
from app.settings import settings

if TYPE_CHECKING:
    from app.api.admin_auth import AdminIdentity


async def require_org_context(
    request: Request, identity: SaaSIdentity | None = Depends(_get_cached_identity)
) -> uuid.UUID:
    admin_identity: AdminIdentity | None = getattr(request.state, "admin_identity", None)
    if admin_identity:
        request.state.current_org_id = admin_identity.org_id
        set_current_org_id(admin_identity.org_id)
        return admin_identity.org_id

    token_present = _get_saas_token(request) is not None

    if identity:
        request.state.current_org_id = identity.org_id
        set_current_org_id(identity.org_id)
        return identity.org_id

    state_org_id = getattr(request.state, "current_org_id", None)
    if state_org_id is not None:
        set_current_org_id(state_org_id)
        return state_org_id

    if token_present:
        error_from_state: HTTPException | None = getattr(request.state, "saas_identity_error", None)
        if error_from_state:
            raise error_from_state
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    if not settings.legacy_basic_auth_enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    return resolve_org_id(request)
