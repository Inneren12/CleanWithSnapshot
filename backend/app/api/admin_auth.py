import base64
import hmac
import logging
import secrets
import time
import uuid
from ipaddress import ip_address, ip_network
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
from app.infra.security import resolve_client_key

PROXY_AUTH_HEADER_SECRET = "X-Proxy-Auth-Secret"
PROXY_E2E_SIGNATURE_HEADER = "X-E2E-Proxy-Signature"
PROXY_E2E_TIMESTAMP_HEADER = "X-E2E-Proxy-Timestamp"
PROXY_E2E_ADMIN_USER_HEADER = "X-E2E-Admin-User"
PROXY_E2E_ADMIN_EMAIL_HEADER = "X-E2E-Admin-Email"
PROXY_E2E_ADMIN_ROLES_HEADER = "X-E2E-Admin-Roles"
MFA_TRUE_VALUES = {"true", "1", "yes"}

logger = logging.getLogger(__name__)

ADMIN_AUTH_FAILURE_REASONS = {
    "untrusted_proxy",
    "proxy_auth_required",
    "bad_signature",
    "mfa_required",
    "invalid_credentials",
    "rate_limited",
}
_ADMIN_AUTH_FAILURE_REASON_MAP = {
    "basic_auth_disabled": "invalid_credentials",
    "bearer_token_present_for_admin": "invalid_credentials",
    "expired_timestamp": "bad_signature",
    "invalid_authentication": "invalid_credentials",
    "invalid_proxy_secret": "bad_signature",
    "malformed_authorization_header": "invalid_credentials",
    "missing_credentials": "invalid_credentials",
    "missing_headers": "proxy_auth_required",
    "missing_username": "invalid_credentials",
    "proxy_auth_failed": "proxy_auth_required",
    "unauthorized": "invalid_credentials",
    "unconfigured_credentials": "invalid_credentials",
}


def _normalize_failure_reason(reason: str | None) -> str:
    if not reason:
        return "invalid_credentials"
    normalized = reason.strip().lower()
    if normalized in ADMIN_AUTH_FAILURE_REASONS:
        return normalized
    return _ADMIN_AUTH_FAILURE_REASON_MAP.get(normalized, "invalid_credentials")


def _resolve_source_ip(request: Request) -> str:
    return resolve_client_key(
        request,
        trust_proxy_headers=settings.trust_proxy_headers,
        trusted_proxy_ips=settings.trusted_proxy_ips,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )


def _resolve_source_cidr(request: Request) -> str | None:
    source_ip = _resolve_source_ip(request)
    try:
        client_ip = ip_address(source_ip)
    except ValueError:
        return None
    prefix = 24 if client_ip.version == 4 else 64
    return str(ip_network(f"{client_ip}/{prefix}", strict=False))


def _parse_roles_list(roles_header: str | None) -> list[str]:
    if not roles_header:
        return []
    return [role.strip().lower() for role in roles_header.split(",") if role.strip()]


class AdminAuthException(HTTPException):
    def __init__(
        self, *, reason: str, detail: str = "Invalid authentication"
    ) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={
                "WWW-Authenticate": "Basic",
                "X-Admin-Auth-Fail-Reason": reason,
            },
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
    mfa_verified: bool = False
    email: str | None = None
    roles: list[str] | None = None


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
    return AdminAuthException(detail=detail, reason=_normalize_failure_reason(reason))


def _resolve_request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return str(request_id)
    return request.headers.get("X-Request-ID")


def _is_trusted_proxy_request(request: Request) -> bool:
    if not settings.trust_proxy_headers:
        return False
    client_host = request.client.host if request.client else "unknown"
    if client_host in settings.trusted_proxy_ips:
        return True
    try:
        client_ip = ip_address(client_host)
    except ValueError:
        return False
    for cidr in settings.trusted_proxy_cidrs:
        try:
            if client_ip in ip_network(cidr):
                return True
        except ValueError:
            continue
    return False


def _build_e2e_signature_payload(
    *,
    user: str,
    email: str,
    roles: str,
    timestamp: str,
    mfa: str,
) -> bytes:
    normalized = "\n".join([user, email, roles, timestamp, mfa])
    return normalized.encode("utf-8")


def _mfa_verified_from_header(request: Request) -> bool:
    header_name = settings.admin_proxy_auth_header_mfa
    raw_value = request.headers.get(header_name, "")
    if not raw_value:
        return False
    return raw_value.strip().lower() in MFA_TRUE_VALUES


def _log_admin_auth_failure(
    request: Request,
    *,
    reason: str,
    credentials: HTTPBasicCredentials | None,
    extra_detail: dict | None = None,
) -> None:
    authorization_header = request.headers.get("Authorization")
    scheme, _ = get_authorization_scheme_param(authorization_header)
    mfa_header = settings.admin_proxy_auth_header_mfa
    normalized_reason = _normalize_failure_reason(reason)
    auth_method = extra_detail.get("auth_method") if extra_detail else None
    roles_header = request.headers.get(settings.admin_proxy_auth_header_roles) or request.headers.get(
        PROXY_E2E_ADMIN_ROLES_HEADER
    )
    parsed_roles = _parse_roles_list(roles_header)
    source_cidr = _resolve_source_cidr(request)
    payload = {
        "event": "admin_auth_attempt",
        "outcome": "failure",
        "event_id": str(uuid.uuid4()),
        "failure_reason": normalized_reason,
        "failure_reason_detail": reason,
        "path": request.url.path,
        "method": request.method,
        "request_id": _resolve_request_id(request),
        "source_ip": _resolve_source_ip(request),
        "source_cidr": source_cidr,
        "user_agent": request.headers.get("User-Agent"),
        "auth_method": auth_method,
        "has_authorization_header": authorization_header is not None,
        "auth_scheme": scheme.lower() if scheme else None,
        "mfa": _mfa_verified_from_header(request),
        "mfa_header": mfa_header,
        "mfa_header_present": bool(request.headers.get(mfa_header)),
        "proxy_trusted": _is_trusted_proxy_request(request),
        "e2e_proxy_signature_present": bool(request.headers.get(PROXY_E2E_SIGNATURE_HEADER)),
        "break_glass": bool(getattr(request.state, "break_glass", False)),
    }
    if credentials and credentials.username:
        payload["admin_user"] = credentials.username
    if parsed_roles:
        payload["roles"] = parsed_roles
    if extra_detail:
        payload.update(extra_detail)
    logger.warning("admin_auth_failed", extra={"extra": payload})
    metrics.record_auth_failure("admin", normalized_reason)
    metrics.record_admin_auth_event(
        outcome="failure",
        method=extra_detail.get("auth_method") if extra_detail else None,
        mfa=_mfa_verified_from_header(request),
        reason=normalized_reason,
    )
    metrics.record_admin_auth_failure(
        method=auth_method,
        reason=normalized_reason,
        source_cidr=source_cidr,
    )
    if payload["break_glass"]:
        metrics.record_admin_break_glass()
    request.state.admin_auth_logged = True


def _log_admin_auth_success(
    request: Request,
    *,
    identity: AdminIdentity,
    auth_method: str,
    roles: list[str],
    mfa_verified: bool,
    email: str | None = None,
    extra_detail: dict | None = None,
) -> None:
    source_cidr = _resolve_source_cidr(request)
    break_glass = bool(getattr(request.state, "break_glass", False))
    payload = {
        "event": "admin_auth_attempt",
        "outcome": "success",
        "event_id": str(uuid.uuid4()),
        "path": request.url.path,
        "method": request.method,
        "request_id": _resolve_request_id(request),
        "source_ip": _resolve_source_ip(request),
        "source_cidr": source_cidr,
        "user_agent": request.headers.get("User-Agent"),
        "admin_user": identity.username,
        "admin_email": email,
        "role": identity.role.value,
        "roles": roles,
        "auth_method": auth_method,
        "mfa": mfa_verified,
        "proxy_trusted": _is_trusted_proxy_request(request),
        "break_glass": break_glass,
    }
    if extra_detail:
        payload.update(extra_detail)
    logger.info("admin_auth_success", extra={"extra": payload})
    metrics.record_admin_auth_event(
        outcome="success",
        method=auth_method,
        mfa=mfa_verified,
        reason=None,
    )
    metrics.record_admin_auth_success(
        method=auth_method,
        mfa=mfa_verified,
        source_cidr=source_cidr,
    )
    if break_glass:
        metrics.record_admin_break_glass()
    request.state.admin_auth_logged = True


def _authenticate_credentials(
    credentials: HTTPBasicCredentials | None,
    *,
    mfa_verified: bool,
    request: Request,
) -> AdminIdentity:
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
            identity = AdminIdentity(
                username=user.username,
                role=user.role,
                org_id=settings.default_org_id,
                admin_id=user.username,
                auth_method="basic",
                mfa_verified=mfa_verified,
                roles=[user.role.value],
            )
            _log_admin_auth_success(
                request,
                identity=identity,
                auth_method="basic",
                roles=[user.role.value],
                mfa_verified=mfa_verified,
                email=None,
            )
            return identity

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


def _require_trusted_proxy(request: Request) -> None:
    if not _is_trusted_proxy_request(request):
        logger.warning(
            "admin_proxy_auth_untrusted",
            extra={
                "extra": {
                    "path": request.url.path,
                    "method": request.method,
                    "client_host": request.client.host if request.client else None,
                }
            },
        )
        raise _build_auth_exception(
            reason="untrusted_proxy",
            detail="Admin access requires a trusted proxy",
        )


def _require_e2e_signature(
    request: Request,
    *,
    user: str,
    email: str,
    roles: str,
) -> None:
    signature = request.headers.get(PROXY_E2E_SIGNATURE_HEADER, "")
    timestamp = request.headers.get(PROXY_E2E_TIMESTAMP_HEADER, "")
    secret = settings.admin_proxy_auth_e2e_secret or ""
    if not signature or not timestamp or not secret:
        raise _build_auth_exception(
            reason="bad_signature",
            detail="Invalid proxy signature",
        )
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise _build_auth_exception(
            reason="bad_signature",
            detail="Invalid proxy signature",
        ) from exc
    now = int(time.time())
    skew = abs(now - timestamp_value)
    if skew > settings.admin_proxy_auth_e2e_ttl_seconds:
        detail = "Proxy signature expired"
        if settings.testing:
            detail = (
                "Proxy signature expired "
                f"(server_now={now}, request_ts={timestamp_value}, skew={skew}s)"
            )
        raise _build_auth_exception(
            reason="expired_timestamp",
            detail=detail,
        )
    mfa_header_value = request.headers.get(settings.admin_proxy_auth_header_mfa, "").strip().lower()
    payload = _build_e2e_signature_payload(
        user=user,
        email=email,
        roles=roles,
        timestamp=timestamp,
        mfa=mfa_header_value,
    )
    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        "sha256",
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise _build_auth_exception(
            reason="bad_signature",
            detail="Invalid proxy signature",
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


def _test_mfa_bypass_enabled() -> bool:
    return bool(getattr(settings, "testing", False) or settings.app_env in {"test", "ci", "e2e"})


def _require_mfa_header(request: Request, *, allow_test_bypass: bool = False) -> bool:
    mfa_verified = _mfa_verified_from_header(request)
    if mfa_verified:
        _require_trusted_proxy(request)
        return mfa_verified
    if allow_test_bypass and _test_mfa_bypass_enabled():
        logger.info(
            "admin_auth_mfa_bypassed_for_testing",
            extra={
                "extra": {
                    "path": request.url.path,
                    "method": request.method,
                    "mfa_header": settings.admin_proxy_auth_header_mfa,
                }
            },
        )
        return True
    _require_trusted_proxy(request)
    logger.warning(
        "admin_auth_mfa_required",
        extra={
            "extra": {
                "path": request.url.path,
                "method": request.method,
                "mfa_header": settings.admin_proxy_auth_header_mfa,
            }
        },
    )
    raise _build_auth_exception(
        reason="mfa_required",
        detail="Admin access requires MFA",
    )


def _resolve_proxy_identity_headers(request: Request) -> tuple[str, str, str, str] | None:
    user_header = settings.admin_proxy_auth_header_user
    email_header = settings.admin_proxy_auth_header_email
    roles_header = settings.admin_proxy_auth_header_roles

    admin_user = request.headers.get(user_header, "").strip()
    admin_email = request.headers.get(email_header, "").strip()
    admin_roles = request.headers.get(roles_header, "").strip()

    has_proxy_headers = bool(admin_user or admin_email)
    if has_proxy_headers:
        if not admin_user:
            raise _build_auth_exception(
                reason="missing_headers",
                detail="Proxy authentication missing required headers",
            )
        return admin_user, admin_email, admin_roles, "proxy"

    if not settings.admin_proxy_auth_e2e_enabled:
        return None

    e2e_user = request.headers.get(PROXY_E2E_ADMIN_USER_HEADER, "").strip()
    e2e_email = request.headers.get(PROXY_E2E_ADMIN_EMAIL_HEADER, "").strip()
    e2e_roles = request.headers.get(PROXY_E2E_ADMIN_ROLES_HEADER, "").strip()
    if not e2e_user:
        return None
    return e2e_user, e2e_email, e2e_roles, "e2e"


def _authenticate_proxy_headers(request: Request) -> AdminIdentity | None:
    """Authenticate admin using trusted proxy headers.

    Returns AdminIdentity if valid proxy headers are present and verified,
    None if proxy auth is not applicable, or raises an exception if
    proxy auth is required but headers are invalid.
    """
    if not settings.admin_proxy_auth_enabled:
        return None

    _require_trusted_proxy(request)
    identity_headers = _resolve_proxy_identity_headers(request)
    if identity_headers is None:
        if settings.admin_proxy_auth_required:
            logger.warning(
                "admin_proxy_auth_required_missing_headers",
                extra={
                    "extra": {
                        "path": request.url.path,
                        "method": request.method,
                    }
                },
            )
            raise _build_auth_exception(
                reason="proxy_auth_required",
                detail="Admin access requires proxy authentication",
            )
        return None

    admin_user, admin_email, admin_roles, source = identity_headers
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

    mfa_verified = _require_mfa_header(request)
    if source == "e2e":
        _require_e2e_signature(
            request,
            user=admin_user,
            email=admin_email,
            roles=admin_roles,
        )
    role = _parse_proxy_roles(admin_roles)
    role_list = _parse_roles_list(admin_roles)

    identity = AdminIdentity(
        username=admin_user,
        role=role,
        org_id=settings.default_org_id,
        admin_id=admin_user,
        auth_method=source,
        mfa_verified=mfa_verified,
        email=admin_email or None,
        roles=role_list or [role.value],
    )
    _log_admin_auth_success(
        request,
        identity=identity,
        auth_method=source,
        roles=role_list or [role.value],
        mfa_verified=mfa_verified,
        email=admin_email or None,
        extra_detail={"auth_method_source": source},
    )

    return identity


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

    try:
        if settings.admin_proxy_auth_enabled:
            proxy_identity = _authenticate_proxy_headers(request)
            if proxy_identity is None:
                raise _build_auth_exception(
                    reason="proxy_auth_required",
                    detail="Admin access requires proxy authentication",
                )
            identity = proxy_identity
        else:
            identity = _authenticate_credentials(credentials, mfa_verified=False, request=request)
    except HTTPException as exc:
        if not getattr(request.state, "admin_auth_logged", False):
            reason = getattr(exc, "reason", None) or "invalid_credentials"
            _log_admin_auth_failure(
                request,
                reason=reason,
                credentials=credentials,
                extra_detail={
                    "auth_method": "proxy" if settings.admin_proxy_auth_enabled else "basic"
                },
            )
        raise

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
        if saas_identity and not settings.admin_proxy_auth_enabled:
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
            _log_admin_auth_failure(
                request,
                reason=reason,
                credentials=None,
                extra_detail={"auth_method": "proxy"},
            )
            return await http_exception_handler(request, exc)

        if settings.admin_proxy_auth_enabled:
            _log_admin_auth_failure(
                request,
                reason="proxy_auth_required",
                credentials=None,
                extra_detail={
                    "proxy_auth_enabled": settings.admin_proxy_auth_enabled,
                    "auth_method": "proxy",
                },
            )
            return await http_exception_handler(
                request,
                _build_auth_exception(
                    reason="proxy_auth_required",
                    detail="Admin access requires proxy authentication",
                ),
            )

        if settings.admin_proxy_auth_required:
            _log_admin_auth_failure(
                request,
                reason="proxy_auth_required",
                credentials=None,
                extra_detail={
                    "proxy_auth_enabled": settings.admin_proxy_auth_enabled,
                    "auth_method": "proxy",
                },
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
                extra_detail={"auth_method": "bearer"},
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
                extra_detail={"configured_user_count": len(configured_users), "auth_method": "basic"},
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
            mfa_verified = _require_mfa_header(request, allow_test_bypass=True)
            identity = _authenticate_credentials(credentials, mfa_verified=mfa_verified, request=request)
            _assert_permissions(request, identity, [AdminPermission.VIEW])
            request.state.admin_identity = identity
            request.state.current_org_id = getattr(request.state, "current_org_id", None) or identity.org_id
            set_current_org_id(request.state.current_org_id)
            return await call_next(request)
        except HTTPException as exc:
            reason = getattr(exc, "reason", None) or "unauthorized"
            if credentials is None:
                reason = reason or "missing_credentials"
            _log_admin_auth_failure(
                request,
                reason=reason,
                credentials=credentials,
                extra_detail={"auth_method": "basic"},
            )
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
