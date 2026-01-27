import base64
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from fastapi import Depends, HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.security.utils import get_authorization_scheme_param
from starlette.middleware.base import BaseHTTPMiddleware

from app.settings import settings
from app.domain.iam import permissions as iam_permissions
from app.infra.logging import update_log_context
from app.infra.metrics import metrics
from app.infra.org_context import set_current_org_id

PROXY_AUTH_HEADER_SECRET = "X-Proxy-Auth-Secret"

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
    admin_id: str | None = None
    auth_method: str | None = None


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
    metrics.record_auth_failure("admin", reason)


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
                username=user.username,
                role=user.role,
                org_id=settings.default_org_id,
                admin_id=user.username,
                auth_method="basic",
            )

    raise _build_auth_exception(reason="invalid_credentials")


def _verify_proxy_secret(request: Request) -> bool:
    """Verify that the request comes from a trusted reverse proxy."""
    if not settings.admin_proxy_auth_secret:
        return False
    provided_secret = request.headers.get(PROXY_AUTH_HEADER_SECRET, "")
    if not provided_secret:
        return False
    return hmac.compare_digest(
        provided_secret.encode("utf-8"),
        settings.admin_proxy_auth_secret.encode("utf-8"),
    )


def _parse_proxy_roles(roles_header: str | None) -> AdminRole:
    """Parse roles from proxy header and return the highest privilege role."""
    if not roles_header:
        return AdminRole.VIEWER
    roles = [r.strip().lower() for r in roles_header.split(",") if r.strip()]
    role_priority = [
        AdminRole.OWNER,
        AdminRole.ADMIN,
        AdminRole.DISPATCHER,
        AdminRole.ACCOUNTANT,
        AdminRole.FINANCE,
        AdminRole.VIEWER,
    ]
    for role in role_priority:
        if role.value in roles:
            return role
    return AdminRole.VIEWER


def _authenticate_proxy_headers(request: Request) -> AdminIdentity | None:
    """Authenticate admin using trusted proxy headers.

    Returns AdminIdentity if valid proxy headers are present and verified,
    None if proxy auth is not applicable, or raises an exception if
    proxy auth is required but headers are invalid.
    """
    if not settings.admin_proxy_auth_enabled:
        return None

    user_header = settings.admin_proxy_auth_header_user
    email_header = settings.admin_proxy_auth_header_email
    roles_header = settings.admin_proxy_auth_header_roles

    admin_user = request.headers.get(user_header, "").strip()
    admin_email = request.headers.get(email_header, "").strip()
    admin_roles = request.headers.get(roles_header, "").strip()

    has_proxy_headers = bool(admin_user or admin_email)

    if not has_proxy_headers:
        if settings.admin_proxy_auth_required:
            logger.warning(
                "admin_proxy_auth_required_missing_headers",
                extra={
                    "extra": {
                        "path": request.url.path,
                        "method": request.method,
                        "has_user_header": bool(admin_user),
                        "has_email_header": bool(admin_email),
                    }
                },
            )
            raise _build_auth_exception(
                reason="proxy_auth_required",
                detail="Admin access requires proxy authentication",
            )
        return None

    if not _verify_proxy_secret(request):
        logger.warning(
            "admin_proxy_auth_invalid_secret",
            extra={
                "extra": {
                    "path": request.url.path,
                    "method": request.method,
                    "has_secret_header": bool(request.headers.get(PROXY_AUTH_HEADER_SECRET)),
                }
            },
        )
        raise _build_auth_exception(
            reason="invalid_proxy_secret",
            detail="Invalid proxy authentication",
        )

    if not admin_user:
        logger.warning(
            "admin_proxy_auth_missing_user",
            extra={
                "extra": {
                    "path": request.url.path,
                    "method": request.method,
                    "has_email": bool(admin_email),
                }
            },
        )
        raise _build_auth_exception(
            reason="missing_proxy_user",
            detail="Proxy authentication missing user identity",
        )

    role = _parse_proxy_roles(admin_roles)

    logger.debug(
        "admin_proxy_auth_success",
        extra={
            "extra": {
                "username": admin_user,
                "email": admin_email,
                "role": role.value,
                "auth_method": "proxy",
            }
        },
    )

    return AdminIdentity(
        username=admin_user,
        role=role,
        org_id=settings.default_org_id,
        admin_id=admin_user,
        auth_method="proxy",
    )


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

    identity: AdminIdentity | None = None

    proxy_identity = _authenticate_proxy_headers(request)
    if proxy_identity is not None:
        identity = proxy_identity
    elif not settings.admin_proxy_auth_required:
        identity = _authenticate_credentials(credentials)
    else:
        raise _build_auth_exception(
            reason="proxy_auth_required",
            detail="Admin access requires proxy authentication",
        )

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

        if saas_identity_error:
            return await http_exception_handler(request, saas_identity_error)

        try:
            proxy_identity = _authenticate_proxy_headers(request)
            if proxy_identity is not None:
                _assert_permissions(request, proxy_identity, [AdminPermission.VIEW])
                request.state.admin_identity = proxy_identity
                request.state.current_org_id = (
                    getattr(request.state, "current_org_id", None) or proxy_identity.org_id
                )
                set_current_org_id(request.state.current_org_id)
                return await call_next(request)
        except HTTPException as exc:
            reason = getattr(exc, "reason", None) or "proxy_auth_failed"
            _log_admin_auth_failure(request, reason=reason, credentials=None)
            return await http_exception_handler(request, exc)

        if settings.admin_proxy_auth_required:
            _log_admin_auth_failure(
                request,
                reason="proxy_auth_required",
                credentials=None,
                extra_detail={"proxy_auth_enabled": settings.admin_proxy_auth_enabled},
            )
            return await http_exception_handler(
                request,
                _build_auth_exception(
                    reason="proxy_auth_required",
                    detail="Admin access requires proxy authentication",
                ),
            )

        authorization: str = request.headers.get("Authorization", "")
        has_bearer = authorization.lower().startswith("bearer ")

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
    READ_METHODS = {"GET", "HEAD"}

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        is_admin_path = path.startswith("/v1/admin")
        should_audit_write = is_admin_path and request.method in self.SENSITIVE_METHODS
        request.state.explicit_admin_audit = False

        response = await call_next(request)
        already_logged = getattr(request.state, "explicit_admin_audit", False)

        if not is_admin_path or already_logged:
            return response

        from app.domain.admin_audit import policy as audit_policy
        from app.domain.admin_audit import service as audit_service
        from app.domain.admin_audit.db_models import AdminAuditActionType, AdminAuditSensitivity

        identity: AdminIdentity | None = getattr(request.state, "admin_identity", None)
        if identity is None:
            return response

        action_type = None
        sensitivity = None
        resource_type = None
        resource_id = None

        if should_audit_write:
            action_type = AdminAuditActionType.WRITE
            sensitivity = AdminAuditSensitivity.NORMAL
        elif request.method in self.READ_METHODS:
            classification = audit_policy.classify_sensitive_read(path)
            if classification:
                resource_type, resource_id, sensitivity = classification
                action_type = AdminAuditActionType.READ

        if action_type is None:
            return response

        session_factory = getattr(request.app.state, "db_session_factory", None)
        if session_factory is None:
            return response

        try:
            async with session_factory() as session:
                await audit_service.audit_admin_action(
                    session,
                    identity=identity,
                    action=f"{request.method} {path}",
                    action_type=action_type,
                    sensitivity_level=sensitivity,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    before=None,
                    after=None,
                )
                await session.commit()
                request.state.explicit_admin_audit = True
        except Exception:  # noqa: BLE001
            logger.exception("admin_audit_failed")
            return response
        return response
