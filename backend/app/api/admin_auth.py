import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
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
from app.infra.security import is_trusted_proxy_source
from app.infra.logging import update_log_context
from app.infra.metrics import metrics
from app.infra.org_context import set_current_org_id

logger = logging.getLogger(__name__)

ADMIN_PROXY_USER_HEADER = "X-Admin-User"
ADMIN_PROXY_EMAIL_HEADER = "X-Admin-Email"
ADMIN_PROXY_ROLES_HEADER = "X-Admin-Roles"
ADMIN_PROXY_AUTH_HEADER = "X-Proxy-Auth"
E2E_PROXY_USER_HEADER = "X-Proxy-Admin-User"
E2E_PROXY_EMAIL_HEADER = "X-Proxy-Admin-Email"
E2E_PROXY_ROLES_HEADER = "X-Proxy-Admin-Roles"
E2E_PROXY_TIMESTAMP_HEADER = "X-Proxy-Admin-Timestamp"
E2E_PROXY_SIGNATURE_HEADER = "X-Proxy-Admin-Signature"
E2E_PROXY_CLOCK_SKEW_SECONDS = 60
ADMIN_IDENTITY_SOURCE_PROXY = "proxy"
ADMIN_IDENTITY_SOURCE_SAAS = "saas"
ADMIN_IDENTITY_SOURCE_BASIC = "basic"
ADMIN_AUTH_FAIL_HEADER = "X-Admin-Auth-Fail-Reason"
ADMIN_AUTH_FAIL_REASONS = {
    "untrusted_proxy",
    "bad_signature",
    "missing_headers",
    "expired_timestamp",
    "proxy_disabled",
}
ADMIN_AUTH_FAIL_ENVS = {"ci", "e2e", "dev", "local", "test"}


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


def _build_proxy_auth_exception(
    *, detail: str = "Admin access requires proxy authentication", reason: str = "untrusted_proxy"
) -> HTTPException:
    exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
    setattr(exc, "reason", reason)
    return exc


def _resolve_request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return str(request_id)
    return request.headers.get("X-Request-ID")


def _set_admin_identity(request: Request, identity: AdminIdentity, source: str) -> None:
    request.state.admin_identity = identity
    request.state.admin_identity_source = source
    request.state.current_org_id = getattr(request.state, "current_org_id", None) or identity.org_id
    set_current_org_id(request.state.current_org_id)


def _is_e2e_proxy_auth_allowed() -> bool:
    if not settings.e2e_proxy_auth_enabled:
        return False
    if not settings.admin_proxy_auth_enabled:
        return False
    if not settings.trust_proxy_headers:
        return False
    if settings.app_env == "prod":
        return False
    return bool(settings.testing or os.getenv("CI", "").lower() == "true")


def _should_emit_admin_auth_reason() -> bool:
    return settings.app_env in ADMIN_AUTH_FAIL_ENVS


def _attach_admin_auth_fail_reason(response, reason: str | None):
    if not reason or reason not in ADMIN_AUTH_FAIL_REASONS:
        return response
    if _should_emit_admin_auth_reason():
        response.headers[ADMIN_AUTH_FAIL_HEADER] = reason
    return response


def _ensure_trusted_proxy_source(request: Request) -> None:
    if not settings.admin_proxy_auth_enabled:
        raise _build_proxy_auth_exception(reason="proxy_disabled")
    if not settings.trust_proxy_headers:
        raise _build_proxy_auth_exception(reason="untrusted_proxy")
    if not is_trusted_proxy_source(
        request,
        settings.trusted_proxy_ips,
        settings.trusted_proxy_cidrs,
    ):
        raise _build_proxy_auth_exception(reason="untrusted_proxy")


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


def _role_from_proxy_headers(roles_header: str | None, username: str) -> AdminRole:
    role_map = {role.value: role for role in AdminRole}
    if roles_header:
        roles = [value.strip().lower() for value in roles_header.split(",") if value.strip()]
        for preferred in (
            AdminRole.OWNER,
            AdminRole.ADMIN,
            AdminRole.FINANCE,
            AdminRole.ACCOUNTANT,
            AdminRole.DISPATCHER,
            AdminRole.VIEWER,
        ):
            if preferred.value in roles:
                return preferred
        for role in roles:
            if role in role_map:
                return role_map[role]

    normalized = username.strip().lower()
    if normalized == AdminRole.VIEWER.value:
        return AdminRole.VIEWER
    if normalized == AdminRole.DISPATCHER.value:
        return AdminRole.DISPATCHER
    if normalized == AdminRole.ACCOUNTANT.value:
        return AdminRole.ACCOUNTANT
    if normalized == AdminRole.FINANCE.value:
        return AdminRole.FINANCE
    return AdminRole.ADMIN


def _authenticate_proxy_headers(request: Request) -> AdminIdentity:
    proxy_auth = request.headers.get(ADMIN_PROXY_AUTH_HEADER)
    if proxy_auth != "1":
        raise _build_proxy_auth_exception(reason="missing_headers")
    user = request.headers.get(ADMIN_PROXY_USER_HEADER)
    email = request.headers.get(ADMIN_PROXY_EMAIL_HEADER)
    roles = request.headers.get(ADMIN_PROXY_ROLES_HEADER)
    if not user or not email or not roles:
        raise _build_proxy_auth_exception(reason="missing_headers")
    username = user or email or "unknown"
    role = _role_from_proxy_headers(roles, username)
    return AdminIdentity(
        username=username,
        role=role,
        org_id=settings.default_org_id,
        admin_id=email or username,
        auth_method="proxy",
    )


def _has_e2e_proxy_headers(request: Request) -> bool:
    return all(
        request.headers.get(header)
        for header in (
            E2E_PROXY_USER_HEADER,
            E2E_PROXY_EMAIL_HEADER,
            E2E_PROXY_TIMESTAMP_HEADER,
            E2E_PROXY_SIGNATURE_HEADER,
        )
    )


def _has_proxy_headers(request: Request) -> bool:
    return any(
        request.headers.get(header)
        for header in (
            ADMIN_PROXY_AUTH_HEADER,
            ADMIN_PROXY_USER_HEADER,
            ADMIN_PROXY_EMAIL_HEADER,
            ADMIN_PROXY_ROLES_HEADER,
            E2E_PROXY_USER_HEADER,
            E2E_PROXY_EMAIL_HEADER,
            E2E_PROXY_TIMESTAMP_HEADER,
            E2E_PROXY_SIGNATURE_HEADER,
        )
    )


def _authenticate_e2e_proxy_headers(request: Request) -> AdminIdentity:
    if not settings.admin_proxy_auth_enabled:
        raise _build_proxy_auth_exception(reason="proxy_disabled")
    if not _is_e2e_proxy_auth_allowed():
        raise _build_proxy_auth_exception(reason="untrusted_proxy")
    secret = settings.e2e_proxy_auth_secret
    if not secret:
        raise _build_proxy_auth_exception(reason="untrusted_proxy")
    user = request.headers.get(E2E_PROXY_USER_HEADER)
    email = request.headers.get(E2E_PROXY_EMAIL_HEADER)
    roles = request.headers.get(E2E_PROXY_ROLES_HEADER, "")
    timestamp_raw = request.headers.get(E2E_PROXY_TIMESTAMP_HEADER)
    signature = request.headers.get(E2E_PROXY_SIGNATURE_HEADER)
    if not user or not email or not timestamp_raw or not signature:
        raise _build_proxy_auth_exception(reason="missing_headers")
    try:
        timestamp = int(timestamp_raw)
    except ValueError:
        raise _build_proxy_auth_exception(reason="missing_headers")
    now = int(time.time())
    if abs(now - timestamp) > E2E_PROXY_CLOCK_SKEW_SECONDS:
        raise _build_proxy_auth_exception(reason="expired_timestamp")
    canonical = f"{user}|{email}|{roles}|{timestamp}"
    expected = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise _build_proxy_auth_exception(reason="bad_signature")
    role = _role_from_proxy_headers(roles, user)
    return AdminIdentity(
        username=user,
        role=role,
        org_id=settings.default_org_id,
        admin_id=email or user,
        auth_method="e2e-proxy",
    )


def _authenticate_admin_via_proxy(request: Request) -> AdminIdentity:
    _ensure_trusted_proxy_source(request)
    if _has_e2e_proxy_headers(request):
        return _authenticate_e2e_proxy_headers(request)
    return _authenticate_proxy_headers(request)


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
    identity_source = getattr(request.state, "admin_identity_source", None)
    if settings.admin_proxy_auth_enabled and request.url.path.startswith("/v1/admin"):
        if cached and identity_source and identity_source != ADMIN_IDENTITY_SOURCE_PROXY:
            raise _build_proxy_auth_exception(reason="admin_identity_source_mismatch")
        if cached and identity_source == ADMIN_IDENTITY_SOURCE_PROXY:
            org_for_log = getattr(request.state, "current_org_id", None) or cached.org_id
            payload: dict[str, str] = {"role": getattr(cached.role, "value", str(cached.role))}
            if org_for_log:
                payload["org_id"] = str(org_for_log)
            update_log_context(**payload)
            return cached
        identity = _authenticate_admin_via_proxy(request)
        _set_admin_identity(request, identity, ADMIN_IDENTITY_SOURCE_PROXY)
    else:
        if cached:
            org_for_log = getattr(request.state, "current_org_id", None) or cached.org_id
            payload = {"role": getattr(cached.role, "value", str(cached.role))}
            if org_for_log:
                payload["org_id"] = str(org_for_log)
            update_log_context(**payload)
            return cached
        identity = _authenticate_credentials(credentials)
        _set_admin_identity(request, identity, ADMIN_IDENTITY_SOURCE_BASIC)
    org_for_log = getattr(request.state, "current_org_id", None) or identity.org_id
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
        identity_source = getattr(request.state, "admin_identity_source", None)
        if cached and (not settings.admin_proxy_auth_enabled or identity_source == ADMIN_IDENTITY_SOURCE_PROXY):
            return await call_next(request)

        saas_identity_error: HTTPException | None = getattr(request.state, "saas_identity_error", None)
        if saas_identity_error:
            return await http_exception_handler(request, saas_identity_error)

        if not settings.admin_proxy_auth_enabled and _has_proxy_headers(request):
            reason = "proxy_disabled"
            _log_admin_auth_failure(request, reason=reason, credentials=None)
            response = await http_exception_handler(
                request, _build_proxy_auth_exception(reason=reason)
            )
            return _attach_admin_auth_fail_reason(response, reason)

        authorization: str = request.headers.get("Authorization", "")
        has_bearer = authorization.lower().startswith("bearer ")

        if settings.admin_proxy_auth_enabled:
            if cached and identity_source and identity_source != ADMIN_IDENTITY_SOURCE_PROXY:
                _log_admin_auth_failure(
                    request,
                    reason="admin_identity_source_mismatch",
                    credentials=None,
                )
                return await http_exception_handler(
                    request,
                    _build_proxy_auth_exception(reason="admin_identity_source_mismatch"),
                )
            if has_bearer:
                _log_admin_auth_failure(
                    request,
                    reason="bearer_token_present_for_admin",
                    credentials=None,
                )
            try:
                identity = _authenticate_admin_via_proxy(request)
                _assert_permissions(request, identity, [AdminPermission.VIEW])
                _set_admin_identity(request, identity, ADMIN_IDENTITY_SOURCE_PROXY)
                return await call_next(request)
            except HTTPException as exc:
                reason = getattr(exc, "reason", None) or "proxy_auth_required"
                _log_admin_auth_failure(request, reason=reason, credentials=None)
                response = await http_exception_handler(request, exc)
                return _attach_admin_auth_fail_reason(response, reason)

        saas_identity = getattr(request.state, "saas_identity", None)
        if saas_identity:
            return await call_next(request)

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
            _set_admin_identity(request, identity, ADMIN_IDENTITY_SOURCE_BASIC)
            return await call_next(request)
        except HTTPException as exc:
            reason = getattr(exc, "reason", None) or "unauthorized"
            if credentials is None:
                reason = reason or "missing_credentials"
            _log_admin_auth_failure(request, reason=reason, credentials=credentials)
            response = await http_exception_handler(request, exc)
            return _attach_admin_auth_fail_reason(response, reason)


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
