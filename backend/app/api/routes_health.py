import logging
import time
from datetime import datetime, timezone
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.domain.ops.db_models import JobHeartbeat

router = APIRouter()
logger = logging.getLogger(__name__)


_HEAD_CACHE: dict[str, Any] = {"timestamp": 0.0, "heads": None, "skip_reason": None, "warning_logged": False}
_HEAD_CACHE_TTL_SECONDS = 60


def _load_expected_heads() -> tuple[list[str] | None, str | None]:
    """Load expected Alembic heads with a short-lived cache.

    Returns a tuple of (heads, skip_reason). When Alembic metadata is unavailable
    (e.g., packaged deployments without migration files), heads is None and
    skip_reason is populated so callers can treat migrations as skipped.
    """

    now = time.monotonic()
    if now - _HEAD_CACHE["timestamp"] < _HEAD_CACHE_TTL_SECONDS:
        return _HEAD_CACHE["heads"], _HEAD_CACHE["skip_reason"]

    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "alembic")
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        _HEAD_CACHE.update({"timestamp": now, "heads": heads, "skip_reason": None})
        return heads, None
    except Exception as exc:  # noqa: BLE001
        skip_reason = "skipped_no_alembic_files"
        if not _HEAD_CACHE["warning_logged"]:
            logger.warning(
                "migrations_check_skipped_no_alembic_files",
                extra={
                    "extra": {
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "reason": "alembic config or script directory missing",
                    }
                },
            )
            _HEAD_CACHE["warning_logged"] = True
        _HEAD_CACHE.update({"timestamp": now, "heads": None, "skip_reason": skip_reason})
        return None, skip_reason


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}

from fastapi import Response

@router.head("/healthz")
async def healthz_head() -> Response:
    return Response(status_code=200)


async def _get_current_revision(session) -> str | None:
    try:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
    except SQLAlchemyError:
        return None

    row = result.first()
    return row[0] if row else None


async def _check_database(request: Request) -> dict[str, Any]:
    """Check database connectivity with timing."""
    start = time.monotonic()
    session_factory = getattr(request.app.state, "db_session_factory", None)

    if session_factory is None:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": "db",
            "ok": False,
            "ms": elapsed_ms,
            "detail": "database session factory unavailable",
        }

    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": "db",
            "ok": True,
            "ms": elapsed_ms,
            "detail": "database reachable",
        }
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        logger.debug("database_check_failed", exc_info=exc)
        return {
            "name": "db",
            "ok": False,
            "ms": elapsed_ms,
            "detail": f"database check failed: {exc.__class__.__name__}",
        }


async def _check_migrations(request: Request) -> dict[str, Any]:
    """Check migration status with timing."""
    start = time.monotonic()
    session_factory = getattr(request.app.state, "db_session_factory", None)
    expected_heads, skip_reason = _load_expected_heads()
    expected_head = expected_heads[0] if expected_heads and len(expected_heads) == 1 else None
    expected_heads = expected_heads or []

    if session_factory is None:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": "migrations",
            "ok": False,
            "ms": elapsed_ms,
            "detail": "database session factory unavailable",
        }

    try:
        async with session_factory() as session:
            current_version = await _get_current_revision(session)
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        logger.debug("migrations_check_failed", exc_info=exc)
        return {
            "name": "migrations",
            "ok": False,
            "ms": elapsed_ms,
            "detail": f"failed to check migrations: {exc.__class__.__name__}",
        }

    migrations_current: bool
    detail: str
    if skip_reason:
        migrations_current = True
        detail = f"migrations check skipped: {skip_reason}"
    elif not expected_heads:
        migrations_current = False
        detail = "no expected migration heads found"
    elif len(expected_heads) == 1:
        migrations_current = current_version == expected_head
        if migrations_current:
            detail = f"migrations current: {current_version}"
        else:
            detail = f"migration mismatch: current={current_version}, expected={expected_head}"
    else:
        migrations_current = current_version in expected_heads
        if migrations_current:
            detail = f"migrations current: {current_version}"
        else:
            detail = f"migration mismatch: current={current_version}, expected one of {expected_heads}"

    elapsed_ms = round((time.monotonic() - start) * 1000, 1)
    return {
        "name": "migrations",
        "ok": migrations_current,
        "ms": elapsed_ms,
        "detail": detail,
    }


async def _check_jobs(request: Request) -> dict[str, Any]:
    """Check job heartbeat status with timing."""
    start = time.monotonic()
    app_settings = getattr(request.app.state, "app_settings", None)
    heartbeat_required = bool(getattr(app_settings, "job_heartbeat_required", False)) if app_settings else False

    if not heartbeat_required:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": "jobs",
            "ok": True,
            "ms": elapsed_ms,
            "detail": "job heartbeat check disabled",
        }

    session_factory = getattr(request.app.state, "db_session_factory", None)
    if session_factory is None:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": "jobs",
            "ok": False,
            "ms": elapsed_ms,
            "detail": "database session factory unavailable",
        }

    ttl_seconds = int(getattr(app_settings, "job_heartbeat_ttl_seconds", 300)) if app_settings else 300
    try:
        async with session_factory() as session:
            record = await session.get(JobHeartbeat, "jobs-runner")
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        logger.debug("jobs_check_failed", exc_info=exc)
        return {
            "name": "jobs",
            "ok": False,
            "ms": elapsed_ms,
            "detail": f"job heartbeat check failed: {type(exc).__name__}",
        }

    if record is None:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": "jobs",
            "ok": False,
            "ms": elapsed_ms,
            "detail": f"job heartbeat missing (threshold: {ttl_seconds}s)",
        }

    last_seen = record.last_heartbeat
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)

    age_seconds = (datetime.now(tz=timezone.utc) - last_seen).total_seconds()
    elapsed_ms = round((time.monotonic() - start) * 1000, 1)

    is_ok = age_seconds <= ttl_seconds
    if is_ok:
        detail = f"job heartbeat healthy (age: {round(age_seconds, 1)}s, threshold: {ttl_seconds}s)"
    else:
        detail = f"job heartbeat stale (age: {round(age_seconds, 1)}s, threshold: {ttl_seconds}s)"

    return {
        "name": "jobs",
        "ok": is_ok,
        "ms": elapsed_ms,
        "detail": detail,
    }


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness endpoint with structured checks and timing.

    Returns HTTP 200 when all checks pass, HTTP 503 otherwise.
    Response includes per-check status, timing, and details.
    """
    db_check = await _check_database(request)
    migrations_check = await _check_migrations(request)
    jobs_check = await _check_jobs(request)

    checks = [db_check, migrations_check, jobs_check]
    overall_ok = all(check["ok"] for check in checks)
    status_code = 200 if overall_ok else 503

    payload = {
        "ok": overall_ok,
        "checks": checks,
    }
    return JSONResponse(status_code=status_code, content=payload)
