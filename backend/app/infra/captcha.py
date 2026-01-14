from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
CAPTCHA_UNAVAILABLE_LOG_INTERVAL_SECONDS = 300
_last_unavailable_log = 0.0


def log_captcha_event(
    outcome: str,
    *,
    request_id: str | None = None,
    mode: str | None = None,
    provider: str | None = None,
) -> None:
    logger.info(
        "captcha_verification",
        extra={
            "extra": {
                "outcome": outcome,
                "mode": mode,
                "provider": provider,
                "request_id": request_id,
            }
        },
    )


def log_captcha_unavailable(
    reason: str,
    *,
    request_id: str | None = None,
    mode: str | None = None,
) -> None:
    global _last_unavailable_log
    now = time.monotonic()
    if now - _last_unavailable_log < CAPTCHA_UNAVAILABLE_LOG_INTERVAL_SECONDS:
        return
    _last_unavailable_log = now
    logger.error(
        "captcha_unavailable",
        extra={
            "extra": {
                "reason": reason,
                "mode": mode,
                "request_id": request_id,
            }
        },
    )


async def verify_turnstile(
    token: str | None,
    remote_ip: str | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    if not settings.captcha_enabled:
        if settings.app_env == "prod":
            logger.warning("captcha_disabled_in_prod")
        return True

    if settings.captcha_mode == "off":
        return True

    if settings.captcha_mode != "turnstile":
        logger.warning("captcha_mode_unknown", extra={"extra": {"mode": settings.captcha_mode}})
        return False

    if not token:
        return False
    if not settings.turnstile_secret_key:
        logger.warning("turnstile_secret_missing")
        return False

    try:
        async with httpx.AsyncClient(timeout=5, transport=transport) as client:
            response = await client.post(
                TURNSTILE_VERIFY_URL,
                data={"secret": settings.turnstile_secret_key, "response": token, "remoteip": remote_ip},
            )
        payload: dict[str, Any] = response.json()
    except Exception:  # noqa: BLE001
        logger.warning("turnstile_verify_failed")
        return False

    return bool(payload.get("success"))
