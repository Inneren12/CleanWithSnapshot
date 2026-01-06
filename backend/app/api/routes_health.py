import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.domain.ops.db_models import JobHeartbeat

router = APIRouter()
logger = logging.getLogger(__name__)


_HEAD_CACHE: dict[str, Any] = {"timestamp": 0.0, "heads": None, "skip_reason": None, "warning_logged": False}
_HEAD_CACHE_TTL_SECONDS = 60
_DB_CHECK_TIMEOUT_SECONDS = 2.0


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


async def _db_check(request: Request) -> tuple[bool, dict[str, Any]]:
    session_factory = getattr(request.app.state, "db_session_factory", None)
    if session_factory is None:
        return False, {
            "message": "database session factory unavailable",
            "hint": "app.state.db_session_factory is not configured; ensure startup wiring is complete.",
        }

    async def _ping_db():
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_ping_db(), timeout=_DB_CHECK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return False, {"message": "database check timed out", "timeout_seconds": _DB_CHECK_TIMEOUT_SECONDS}
    except Exception as exc:  # noqa: BLE001
        logger.debug("database_check_failed", exc_info=exc)
        return False, {"message": "database check failed", "error": exc.__class__.__name__}

    return True, {"message": "database reachable"}


async def _migrations_check(request: Request) -> tuple[bool, dict[str, Any]]:
    session_factory = getattr(request.app.state, "db_session_factory", None)
    expected_heads, skip_reason = _load_expected_heads()
    expected_head = expected_heads[0] if expected_heads and len(expected_heads) == 1 else None
    expected_heads = expected_heads or []

    if session_factory is None:
        return False, {
            "message": "database session factory unavailable",
            "current_version": None,
            "expected_head": expected_head,
            "expected_heads": expected_heads,
            "migrations_check": skip_reason or "not_run",
        }

    current_version = None

    async def _fetch_version():
        nonlocal current_version
        async with session_factory() as session:
            current_version = await _get_current_revision(session)

    try:
        await asyncio.wait_for(_fetch_version(), timeout=_DB_CHECK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return False, {
            "message": "migration check timed out",
            "current_version": current_version,
            "expected_head": expected_head,
            "expected_heads": expected_heads,
            "migrations_check": skip_reason or "timeout",
            "timeout_seconds": _DB_CHECK_TIMEOUT_SECONDS,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("migration_check_failed", exc_info=exc)
        return False, {
            "message": "migration check failed",
            "current_version": current_version,
            "expected_head": expected_head,
            "expected_heads": expected_heads,
            "migrations_check": skip_reason or "error",
            "error": exc.__class__.__name__,
        }

    migrations_current: bool
    if skip_reason:
        migrations_current = True
    elif not expected_heads:
        migrations_current = False
    elif len(expected_heads) == 1:
        migrations_current = current_version == expected_head
    else:
        migrations_current = current_version in expected_heads

    return migrations_current, {
        "message": "migrations in sync" if migrations_current else "migrations pending",
        "migrations_current": migrations_current,
        "current_version": current_version,
        "expected_head": expected_head,
        "expected_heads": expected_heads,
        "migrations_check": skip_reason or "ok",
    }


async def _jobs_status(request: Request) -> tuple[bool, dict[str, Any]]:
    app_settings = getattr(request.app.state, "app_settings", None)
    heartbeat_required = bool(getattr(app_settings, "job_heartbeat_required", False)) if app_settings else False
    if not heartbeat_required:
        return True, {"enabled": False, "message": "job heartbeat check disabled"}

    session_factory = getattr(request.app.state, "db_session_factory", None)
    if session_factory is None:
        return False, {"enabled": True, "message": "database session factory unavailable"}

    ttl_seconds = int(getattr(app_settings, "job_heartbeat_ttl_seconds", 300)) if app_settings else 300

    async def _fetch_heartbeat():
        async with session_factory() as session:
            return await session.get(JobHeartbeat, "jobs-runner")

    try:
        record = await asyncio.wait_for(_fetch_heartbeat(), timeout=_DB_CHECK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return False, {"enabled": True, "message": "job heartbeat check timed out", "timeout_seconds": _DB_CHECK_TIMEOUT_SECONDS}
    except Exception as exc:  # noqa: BLE001
        logger.debug("jobs_check_failed", exc_info=exc)
        return False, {"enabled": True, "message": "job heartbeat check failed", "error": type(exc).__name__}

    if record is None:
        return False, {
            "enabled": True,
            "message": "job heartbeat missing",
            "threshold_seconds": ttl_seconds,
        }

    last_seen = record.last_heartbeat
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)

    age_seconds = (datetime.now(tz=timezone.utc) - last_seen).total_seconds()
    ok = age_seconds <= ttl_seconds
    return ok, {
        "enabled": True,
        "last_heartbeat": last_seen.isoformat(),
        "age_seconds": age_seconds,
        "threshold_seconds": ttl_seconds,
    }


async def _run_check(name: str, check_fn) -> dict[str, Any]:  # noqa: ANN001
    start = time.perf_counter()
    ok: bool
    detail: dict[str, Any]
    try:
        ok, detail = await check_fn()
    except Exception as exc:  # noqa: BLE001
        logger.exception("readiness_check_failed", extra={"extra": {"check": name}})
        ok = False
        detail = {"message": "unexpected error", "error": type(exc).__name__}
    elapsed_ms = (time.perf_counter() - start) * 1000
    return {"name": name, "ok": bool(ok), "ms": round(elapsed_ms, 2), "detail": detail}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    checks = [
        await _run_check("db", lambda: _db_check(request)),
        await _run_check("migrations", lambda: _migrations_check(request)),
        await _run_check("jobs", lambda: _jobs_status(request)),
    ]

    overall_ok = all(check["ok"] for check in checks)
    status_code = 200 if overall_ok else 503

    payload = {"ok": overall_ok, "checks": checks}
    return JSONResponse(status_code=status_code, content=payload)
