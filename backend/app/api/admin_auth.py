import base64
import logging
import secrets
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.security.utils import get_authorization_scheme_param
from starlette.middleware.base import BaseHTTPMiddleware

from app.settings import settings
from app.domain.iam import permissions as iam_permissions
from app.infra.logging import update_log_context
from app.infra.org_context import set_current_org_id

logger = logging.getLogger(__name__)


class AdminAuthException(HTTPException):
    def __init__(
        self, *, reason: str, detail: str = "Invalid authentication"
    ) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Basic"},
        )
        self.reason = reason


class AdminRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    DISPATCHER = "dispatcher"
    ACCOUNTANT = "accountant"
    FINANCE = "finance"
    VIEWER = "viewer"


class AdminPermission(str, Enum):
    VIEW = "view"
    DISPATCH = "dispatch"
    FINANCE = "finance"
    ADMIN = "admin"


ROLE_PERMISSIONS: dict[AdminRole, set[AdminPermission]] = {
    AdminRole.OWNER: {AdminPermission.VIEW, AdminPermission.DISPATCH, AdminPermission.FINANCE, AdminPermission.ADMIN},
    AdminRole.ADMIN: {AdminPermission.VIEW, AdminPermission.DISPATCH, AdminPermission.FINANCE, AdminPermission.ADMIN},
    AdminRole.DISPATCHER: {AdminPermission.VIEW, AdminPermission.DISPATCH},
    AdminRole.ACCOUNTANT: {AdminPermission.VIEW, AdminPermission.FINANCE},
    AdminRole.FINANCE: {AdminPermission.VIEW, AdminPermission.FINANCE},
    AdminRole.VIEWER: {AdminPermission.VIEW},
}


@dataclass
class AdminIdentity:
    username: str
    role: AdminRole
    org_id: uuid.UUID | None = None


@dataclass
class _ConfiguredUser:
    username: str
    password: str
    role: AdminRole


security = HTTPBasic(auto_error=False)


def _configured_users() -> list[_ConfiguredUser]:
    configured: list[_ConfiguredUser] = []
    def _role_override(username: str, default_role: AdminRole) -> AdminRole:
        normalized = username.strip().lower()
        if normalized == AdminRole.VIEWER.value:
            return AdminRole.VIEWER
        if normalized == AdminRole.DISPATCHER.value:
            return AdminRole.DISPATCHER
        if normalized == AdminRole.ACCOUNTANT.value:
            return AdminRole.ACCOUNTANT
        if normalized == AdminRole.FINANCE.value:
            return AdminRole.FINANCE
        return default_role

    if settings.owner_basic_username and settings.owner_basic_password:
        configured.append(
            _ConfiguredUser(
                username=settings.owner_basic_username,
                password=settings.owner_basic_password,
                role=AdminRole.OWNER,
            )
        )
    if settings.admin_basic_username and settings.admin_basic_password:
        configured.append(
            _ConfiguredUser(
                username=settings.admin_basic_username,
                password=settings.admin_basic_password,
                role=_role_override(settings.admin_basic_username, AdminRole.ADMIN),
            )
        )
    if settings.dispatcher_basic_username and settings.dispatcher_basic_password:
        configured.append(
            _ConfiguredUser(
                username=settings.dispatcher_basic_username,
                password=settings.dispatcher_basic_password,
                role=AdminRole.DISPATCHER,
            )
        )
    if settings.accountant_basic_username and settings.accountant_basic_password:
        configured.append(
            _ConfiguredUser(
                username=settings.accountant_basic_username,
                password=settings.accountant_basic_password,
                role=AdminRole.ACCOUNTANT,
            )
        )
    if settings.viewer_basic_username and settings.viewer_basic_password:
        configured.append(
            _ConfiguredUser(
                username=settings.viewer_basic_username,
                password=settings.viewer_basic_password,
                role=AdminRole.VIEWER,
            )
        )
    return configured


def _build_auth_exception(
    *, detail: str = "Invalid authentication", reason: str = "invalid_authentication"
) -> AdminAuthException:
    return AdminAuthException(detail=detail, reason=reason)


def _resolve_request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return str(request_id)
    return request.headers.get("X-Request-ID")


def _log_admin_auth_failure(
    request: Request,
    *,
    reason: str,
    credentials: HTTPBasicCredentials | None,
    extra_detail: dict | None = None,
) -> None:
    authorization_header = request.headers.get("Authorization")
    scheme, _ = get_authorization_scheme_param(authorization_header)
    payload = {
        "reason": reason,
        "path": request.url.path,
        "method": request.method,
        "request_id": _resolve_request_id(request),
        "has_authorization_header": authorization_header is not None,
        "auth_scheme": scheme.lower() if scheme else None,
    }
    if credentials and credentials.username:
        payload["presented_username"] = credentials.username
    if extra_detail:
        payload.update(extra_detail)
    logger.warning("admin_auth_failed", extra={"extra": payload})


def _authenticate_credentials(credentials: HTTPBasicCredentials | None) -> AdminIdentity:
    configured = _configured_users()
    legacy_basic_auth_enabled = bool(settings.legacy_basic_auth_enabled)
    logger.debug(
        "admin_basic_auth_attempt",
        extra={
            "extra": {
                "legacy_basic_auth_enabled": legacy_basic_auth_enabled,
                "configured_user_count": len(configured),
                "credentials_provided": credentials is not None,
            }
        },
    )
    if not legacy_basic_auth_enabled:
        raise _build_auth_exception(reason="basic_auth_disabled")
    if not configured:
        logger.warning(
            "admin_auth_unconfigured",
            extra={
                "extra": {
                    "path": "/v1/admin",
                    "method": "BASIC",
                    "owner_configured": bool(settings.owner_basic_username and settings.owner_basic_password),
                    "admin_configured": bool(settings.admin_basic_username and settings.admin_basic_password),
                    "dispatcher_configured": bool(
                        settings.dispatcher_basic_username and settings.dispatcher_basic_password
                    ),
                    "accountant_configured": bool(settings.accountant_basic_username and settings.accountant_basic_password),
                    "viewer_configured": bool(settings.viewer_basic_username and settings.viewer_basic_password),
                }
            },
        )
        raise _build_auth_exception(reason="unconfigured_credentials")

    if not credentials:
        raise _build_auth_exception(reason="missing_credentials")

    for user in configured:
        if secrets.compare_digest(credentials.username, user.username) and secrets.compare_digest(
            credentials.password, user.password
        ):
            return AdminIdentity(
                username=user.username, role=user.role, org_id=settings.default_org_id
            )

    raise _build_auth_exception(reason="invalid_credentials")


def _resolve_permission_keys(request: Request, identity: AdminIdentity) -> set[str]:
    saas_identity = getattr(request.state, "saas_identity", None)
    if saas_identity is not None:
        role_key = getattr(saas_identity, "role_key", None) or getattr(
            getattr(saas_identity, "role", None), "value", None
        )
        custom_permissions = getattr(saas_identity, "permission_keys", None)
        return iam_permissions.effective_permissions(
            role_key=role_key,
            custom_permissions=custom_permissions,
        )
    return iam_permissions.permissions_for_role(getattr(identity.role, "value", str(identity.role)))


def permission_keys_for_request(request: Request, identity: AdminIdentity) -> set[str]:
    return _resolve_permission_keys(request, identity)


def _assert_permissions(
    request: Request, identity: AdminIdentity, required: Iterable[AdminPermission]
) -> None:
    permission_keys = _resolve_permission_keys(request, identity)
    required_keys: set[str] = set()
    for permission in required:
        required_keys |= iam_permissions.LEGACY_ADMIN_PERMISSION_MAP.get(
            getattr(permission, "value", str(permission)),
            set(),
        )
    missing = required_keys - permission_keys
    if missing:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def _credentials_from_header(request: Request) -> HTTPBasicCredentials | None:
    authorization: str | None = request.headers.get("Authorization")
    scheme, param = get_authorization_scheme_param(authorization)
    if not authorization or scheme.lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(param).decode("latin1")
    except Exception:  # noqa: BLE001
        raise _build_auth_exception(reason="malformed_authorization_header")
    username, _, password = decoded.partition(":")
    if not username:
        raise _build_auth_exception(reason="missing_username")
    return HTTPBasicCredentials(username=username, password=password)


async def get_admin_identity(
    request: Request, credentials: HTTPBasicCredentials | None = Depends(security)
) -> AdminIdentity:
    cached: AdminIdentity | None = getattr(request.state, "admin_identity", None)
    if cached:
        request.state.current_org_id = getattr(request.state, "current_org_id", None) or cached.org_id
        set_current_org_id(request.state.current_org_id)
        org_for_log = request.state.current_org_id
        payload: dict[str, str] = {"role": getattr(cached.role, "value", str(cached.role))}
        if org_for_log:
            payload["org_id"] = str(org_for_log)
        update_log_context(**payload)
        return cached
    identity = _authenticate_credentials(credentials)
    request.state.admin_identity = identity
    request.state.current_org_id = getattr(request.state, "current_org_id", None) or identity.org_id
    set_current_org_id(request.state.current_org_id)
    org_for_log = request.state.current_org_id
    payload = {"role": getattr(identity.role, "value", str(identity.role))}
    if org_for_log:
        payload["org_id"] = str(org_for_log)
    update_log_context(**payload)
    return identity


def require_permissions(*permissions: AdminPermission):
    async def _require(
        request: Request, identity: AdminIdentity = Depends(get_admin_identity)
    ) -> AdminIdentity:
        _assert_permissions(request, identity, permissions or [AdminPermission.VIEW])
        return identity

    return _require


def require_permission_keys(*permission_keys: str):
    async def _require(
        request: Request, identity: AdminIdentity = Depends(get_admin_identity)
    ) -> AdminIdentity:
        granted = _resolve_permission_keys(request, identity)
        missing = {key for key in permission_keys if key} - granted
        if missing:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return identity

    return _require


def require_any_permission_keys(*permission_keys: str):
    async def _require(
        request: Request, identity: AdminIdentity = Depends(get_admin_identity)
    ) -> AdminIdentity:
        granted = _resolve_permission_keys(request, identity)
        required = {key for key in permission_keys if key}
        if required and granted.isdisjoint(required):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return identity

    return _require


async def require_admin(identity: AdminIdentity = Depends(require_permissions(AdminPermission.ADMIN))) -> AdminIdentity:
    return identity


async def require_dispatch(identity: AdminIdentity = Depends(require_permissions(AdminPermission.DISPATCH))) -> AdminIdentity:
    return identity


async def require_finance(
    identity: AdminIdentity = Depends(require_permissions(AdminPermission.FINANCE)),
) -> AdminIdentity:
    return identity


async def require_viewer(
    identity: AdminIdentity = Depends(require_permissions(AdminPermission.VIEW)),
) -> AdminIdentity:
    return identity


async def verify_admin_or_dispatcher(
    identity: AdminIdentity = Depends(require_permissions(AdminPermission.DISPATCH)),
) -> AdminIdentity:
    return identity


class AdminAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not request.url.path.startswith("/v1/admin"):
            return await call_next(request)

        cached: AdminIdentity | None = getattr(request.state, "admin_identity", None)
        if cached:
            return await call_next(request)

        saas_identity = getattr(request.state, "saas_identity", None)
        if saas_identity:
            return await call_next(request)

        saas_identity_error: HTTPException | None = getattr(request.state, "saas_identity_error", None)
        authorization: str = request.headers.get("Authorization", "")
        has_bearer = authorization.lower().startswith("bearer ")

        if saas_identity_error:
            return await http_exception_handler(request, saas_identity_error)

        if has_bearer:
            _log_admin_auth_failure(
                request,
                reason="bearer_token_present_for_admin",
                credentials=None,
            )
            unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
            return await http_exception_handler(request, unauthorized)

        configured_users = _configured_users()
        basic_auth_enabled = bool(settings.legacy_basic_auth_enabled)

        if not basic_auth_enabled:
            _log_admin_auth_failure(
                request,
                reason="basic_auth_disabled",
                credentials=None,
                extra_detail={"configured_user_count": len(configured_users)},
            )
            logger.debug(
                "admin_basic_auth_disabled",
                extra={
                    "extra": {
                        "configured_user_count": len(configured_users),
                        "legacy_basic_auth_enabled": settings.legacy_basic_auth_enabled,
                    }
                },
            )
            return await http_exception_handler(request, _build_auth_exception())

        credentials: HTTPBasicCredentials | None = None
        try:
            credentials = _credentials_from_header(request)
            identity = _authenticate_credentials(credentials)
            _assert_permissions(request, identity, [AdminPermission.VIEW])
            request.state.admin_identity = identity
            request.state.current_org_id = getattr(request.state, "current_org_id", None) or identity.org_id
            set_current_org_id(request.state.current_org_id)
            return await call_next(request)
        except HTTPException as exc:
            reason = getattr(exc, "reason", None) or "unauthorized"
            if credentials is None:
                reason = reason or "missing_credentials"
            _log_admin_auth_failure(request, reason=reason, credentials=credentials)
            return await http_exception_handler(request, exc)


class AdminAuditMiddleware(BaseHTTPMiddleware):
    SENSITIVE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        should_audit = request.url.path.startswith("/v1/admin") and request.method in self.SENSITIVE_METHODS
        body_bytes: bytes | None = None
        if should_audit:
            body_bytes = await request.body()
            request._body = body_bytes

        request.state.explicit_admin_audit = False
        response = await call_next(request)
        already_logged = getattr(request.state, "explicit_admin_audit", False)

        if should_audit and not already_logged:
            from app.domain.admin_audit import service as audit_service

            identity: AdminIdentity | None = getattr(request.state, "admin_identity", None)
            if identity is None:
                return response

            before = _safe_json(body_bytes)
            raw_after = getattr(response, "body", None)
            after = _safe_json(raw_after if isinstance(raw_after, (bytes, bytearray)) else None)
            session_factory = getattr(request.app.state, "db_session_factory", None)
            if session_factory is None:
                return response
            try:
                async with session_factory() as session:
                    await audit_service.record_action(
                        session,
                        identity=identity,
                        action=f"{request.method} {request.url.path}",
                        resource_type=None,
                        resource_id=None,
                        before=before,
                        after=after,
                    )
                    await session.commit()
            except Exception:  # noqa: BLE001
                logger.exception("admin_audit_failed")
                return response
        return response


def _safe_json(payload: Optional[bytes]) -> dict | list | None:
    if not payload:
        return None
    try:
        import json

        return json.loads(payload.decode())
    except Exception:  # noqa: BLE001
        return None
