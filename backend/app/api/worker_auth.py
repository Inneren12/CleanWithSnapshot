import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.security.utils import get_authorization_scheme_param
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.domain.workers.db_models import Worker
from app.infra.auth import verify_password
from app.infra.db import get_db_session
from app.infra.encryption import blind_hash
from app.settings import settings
from app.infra.logging import update_log_context
from app.infra.org_context import set_current_org_id

logger = logging.getLogger(__name__)


SESSION_COOKIE_NAME = "worker_session"


class WorkerRole(str):
    WORKER = "worker"


@dataclass
class WorkerIdentity:
    username: str
    role: str
    team_id: int
    org_id: uuid.UUID
    worker_id: int | None = None


@dataclass
class _ConfiguredWorker:
    username: str
    password: str
    role: str
    team_id: int
    org_id: uuid.UUID


security = HTTPBasic(auto_error=False)


class WorkerLoginRequest(BaseModel):
    org_id: uuid.UUID


def _configured_workers() -> list[_ConfiguredWorker]:
    configured: list[_ConfiguredWorker] = []
    if settings.worker_basic_username and settings.worker_basic_password:
        configured.append(
            _ConfiguredWorker(
                username=settings.worker_basic_username,
                password=settings.worker_basic_password,
                role=WorkerRole.WORKER,
                team_id=settings.worker_team_id,
                org_id=settings.default_org_id,
            )
        )
    return configured


def _build_auth_exception(detail: str = "Invalid authentication") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Basic"},
    )


def _worker_secret() -> str:
    return settings.worker_portal_secret.get_secret_value()


def _session_token(username: str, role: str, team_id: int, org_id: uuid.UUID) -> str:
    secret = _worker_secret()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.session_ttl_minutes_worker)
    msg = f"{username}:{role}:{team_id}:{org_id}:{int(expires_at.timestamp())}".encode()
    signature = hmac.new(secret.encode(), msg=msg, digestmod=hashlib.sha256).hexdigest()
    return base64.b64encode(
        f"v1:{username}:{role}:{team_id}:{org_id}:{int(expires_at.timestamp())}:{signature}".encode()
    ).decode()


def _session_token_v2(
    username: str, role: str, team_id: int, org_id: uuid.UUID, worker_id: int
) -> str:
    secret = _worker_secret()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.session_ttl_minutes_worker)
    msg = f"{username}:{role}:{team_id}:{org_id}:{worker_id}:{int(expires_at.timestamp())}".encode()
    signature = hmac.new(secret.encode(), msg=msg, digestmod=hashlib.sha256).hexdigest()
    return base64.b64encode(
        f"v2:{username}:{role}:{team_id}:{org_id}:{worker_id}:{int(expires_at.timestamp())}:{signature}".encode()
    ).decode()


def _parse_session_token(token: str | None) -> WorkerIdentity:
    if not token:
        raise _build_auth_exception()
    try:
        decoded = base64.b64decode(token).decode()
        if decoded.startswith("v2:"):
            _, username, role, team_id_raw, org_id_raw, worker_id_raw, expires_raw, signature = decoded.split(
                ":", 7
            )
            expected_payload = (
                f"{username}:{role}:{int(team_id_raw)}:{uuid.UUID(org_id_raw)}:{int(worker_id_raw)}:{int(expires_raw)}"
            )
            expected_sig = hmac.new(
                _worker_secret().encode(), msg=expected_payload.encode(), digestmod=hashlib.sha256
            ).hexdigest()
            if not secrets.compare_digest(signature, expected_sig):
                raise ValueError("Invalid token signature")
            if datetime.now(timezone.utc).timestamp() > int(expires_raw):
                raise ValueError("Session expired")
            return WorkerIdentity(
                username=username,
                role=role,
                team_id=int(team_id_raw),
                org_id=uuid.UUID(org_id_raw),
                worker_id=int(worker_id_raw),
            )
        if decoded.startswith("v1:"):
            _, username, role, team_id_raw, org_id_raw, expires_raw, signature = decoded.split(":", 6)
            expected_payload = f"{username}:{role}:{int(team_id_raw)}:{uuid.UUID(org_id_raw)}:{int(expires_raw)}"
            expected_sig = hmac.new(
                _worker_secret().encode(), msg=expected_payload.encode(), digestmod=hashlib.sha256
            ).hexdigest()
            if not secrets.compare_digest(signature, expected_sig):
                raise ValueError("Invalid token signature")
            if datetime.now(timezone.utc).timestamp() > int(expires_raw):
                raise ValueError("Session expired")
            return WorkerIdentity(
                username=username,
                role=role,
                team_id=int(team_id_raw),
                org_id=uuid.UUID(org_id_raw),
            )
        username, role, team_id_raw, org_id_raw, signature = decoded.split(":", 4)
        expected = _session_token(username, role, int(team_id_raw), uuid.UUID(org_id_raw))
        if not secrets.compare_digest(token, expected):
            raise ValueError("Invalid token signature")
        return WorkerIdentity(
            username=username,
            role=role,
            team_id=int(team_id_raw),
            org_id=uuid.UUID(org_id_raw),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise _build_auth_exception("Invalid session") from exc


def _authenticate_credentials(credentials: HTTPBasicCredentials | None) -> WorkerIdentity:
    """Authenticate worker using environment-configured credentials."""
    configured = _configured_workers()

    if not credentials:
        raise _build_auth_exception()

    # Try environment-based auth first (for backward compatibility)
    for worker in configured:
        if secrets.compare_digest(credentials.username, worker.username) and secrets.compare_digest(
            credentials.password, worker.password
        ):
            return WorkerIdentity(
                username=worker.username,
                role=worker.role,
                team_id=worker.team_id,
                org_id=worker.org_id,
            )

    # If env-based auth fails and no configured workers, raise error
    if not configured:
        logger.warning("worker_auth_unconfigured")

    raise _build_auth_exception()


async def _authenticate_worker_db(
    session: AsyncSession, credentials: HTTPBasicCredentials | None, org_id: uuid.UUID
) -> WorkerIdentity:
    """Authenticate worker using database phone + password."""
    if not credentials:
        raise _build_auth_exception()

    phone = credentials.username
    password = credentials.password

    phone_hash = blind_hash(phone, org_id=org_id)
    stmt = select(Worker).where(
        Worker.phone_blind_index == phone_hash,
        Worker.org_id == org_id,
        Worker.is_active == True,
    )
    result = await session.execute(stmt)
    worker = result.scalar_one_or_none()

    if not worker:
        raise _build_auth_exception("Invalid phone or password")

    # Check if worker has password set
    if not worker.password_hash:
        raise _build_auth_exception("Worker authentication not configured. Please contact your administrator.")

    # Verify password
    is_valid, upgraded_hash = verify_password(password, worker.password_hash, settings=settings)
    if not is_valid:
        raise _build_auth_exception("Invalid phone or password")

    # Auto-upgrade password hash if needed
    if upgraded_hash:
        worker.password_hash = upgraded_hash
        session.add(worker)
        await session.flush()

    return WorkerIdentity(
        username=worker.name,
        role=WorkerRole.WORKER,
        team_id=worker.team_id,
        org_id=worker.org_id,
        worker_id=worker.worker_id,
    )


def _credentials_from_header(request: Request) -> HTTPBasicCredentials | None:
    authorization: str | None = request.headers.get("Authorization")
    scheme, param = get_authorization_scheme_param(authorization)
    if not authorization or scheme.lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(param).decode("latin1")
    except Exception:  # noqa: BLE001
        raise _build_auth_exception()
    username, _, password = decoded.partition(":")
    if not username:
        raise _build_auth_exception()
    return HTTPBasicCredentials(username=username, password=password)


async def get_worker_identity(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_db_session),
) -> WorkerIdentity:
    cached: WorkerIdentity | None = getattr(request.state, "worker_identity", None)
    if cached:
        return cached

    if credentials:
        # Try environment-based auth first
        try:
            identity = _authenticate_credentials(credentials)
        except HTTPException:
            # If env-based auth fails, try database auth
            org_id = getattr(request.state, "current_org_id", None)
            if org_id is None:
                raise _build_auth_exception("Invalid phone or password")
            identity = await _authenticate_worker_db(session, credentials, org_id=org_id)
    else:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        identity = _parse_session_token(token)

    request.state.worker_identity = identity
    request.state.current_org_id = getattr(request.state, "current_org_id", None) or identity.org_id
    set_current_org_id(request.state.current_org_id)
    update_log_context(org_id=str(request.state.current_org_id), user_id=str(identity.username), role=identity.role)
    return identity


async def get_worker_login_identity(
    request: Request,
    login_request: WorkerLoginRequest,
    credentials: HTTPBasicCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_db_session),
) -> WorkerIdentity:
    request.state.current_org_id = login_request.org_id
    set_current_org_id(login_request.org_id)

    try:
        identity = _authenticate_credentials(credentials)
    except HTTPException:
        identity = await _authenticate_worker_db(session, credentials, org_id=login_request.org_id)

    request.state.worker_identity = identity
    update_log_context(org_id=str(login_request.org_id), user_id=str(identity.username), role=identity.role)
    return identity


async def require_worker(identity: WorkerIdentity = Depends(get_worker_identity)) -> WorkerIdentity:
    if identity.role != WorkerRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


class WorkerAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not request.url.path.startswith("/worker"):
            return await call_next(request)
        if request.url.path == "/worker/login":
            return await call_next(request)

        try:
            credentials = _credentials_from_header(request)
            if credentials:
                try:
                    identity = _authenticate_credentials(credentials)
                except HTTPException:
                    session_factory = getattr(request.app.state, "db_session_factory", None)
                    if session_factory is None:
                        raise
                    async with session_factory() as session:
                        org_id = getattr(request.state, "current_org_id", None)
                        if org_id is None:
                            raise _build_auth_exception("Invalid phone or password")
                        identity = await _authenticate_worker_db(session, credentials, org_id=org_id)
            else:
                identity = _parse_session_token(request.cookies.get(SESSION_COOKIE_NAME))
            request.state.worker_identity = identity
            request.state.current_org_id = getattr(request.state, "current_org_id", None) or identity.org_id
            set_current_org_id(request.state.current_org_id)
            update_log_context(
                org_id=str(request.state.current_org_id), user_id=str(identity.username), role=identity.role
            )
            return await call_next(request)
        except HTTPException as exc:
            return await http_exception_handler(request, exc)
