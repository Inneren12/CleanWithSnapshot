from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommunicationResult:
    status: str
    provider_msg_id: str | None = None
    error_code: str | None = None


class NoopCommunicationAdapter:
    async def send_sms(self, *, to_number: str, body: str) -> CommunicationResult:  # noqa: D401
        del to_number, body
        logger.info("sms_send_skipped", extra={"extra": {"mode": "noop"}})
        return CommunicationResult(status="failed", error_code="sms_disabled")

    async def send_call(self, *, to_number: str) -> CommunicationResult:  # noqa: D401
        del to_number
        logger.info("call_send_skipped", extra={"extra": {"mode": "noop"}})
        return CommunicationResult(status="failed", error_code="call_disabled")


class TwilioCommunicationAdapter:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self.http_client = http_client

    async def send_sms(self, *, to_number: str, body: str) -> CommunicationResult:
        if settings.sms_mode != "twilio":
            logger.info("sms_send_skipped", extra={"extra": {"mode": settings.sms_mode}})
            return CommunicationResult(status="failed", error_code="sms_disabled")
        if not _twilio_sms_configured():
            logger.warning("sms_send_not_configured")
            return CommunicationResult(status="failed", error_code="twilio_not_configured")
        url = _twilio_messages_url()
        payload = {"To": to_number, "From": settings.twilio_sms_from, "Body": body}
        return await self._post_twilio(url, payload)

    async def send_call(self, *, to_number: str) -> CommunicationResult:
        if settings.call_mode != "twilio":
            logger.info("call_send_skipped", extra={"extra": {"mode": settings.call_mode}})
            return CommunicationResult(status="failed", error_code="call_disabled")
        if not _twilio_call_configured():
            logger.warning("call_send_not_configured")
            return CommunicationResult(status="failed", error_code="twilio_not_configured")
        url = _twilio_calls_url()
        payload = {"To": to_number, "From": settings.twilio_call_from, "Url": settings.twilio_call_url}
        return await self._post_twilio(url, payload)

    async def _post_twilio(self, url: str, payload: dict[str, str]) -> CommunicationResult:
        client = self.http_client or httpx.AsyncClient()
        close_client = self.http_client is None
        try:
            response = await client.post(
                url,
                data=payload,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                timeout=settings.twilio_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            logger.warning("twilio_request_failed", extra={"extra": {"reason": type(exc).__name__}})
            return CommunicationResult(status="failed", error_code="twilio_request_failed")
        finally:
            if close_client:
                await client.aclose()

        if response.status_code >= 400:
            logger.warning(
                "twilio_request_error",
                extra={"extra": {"status_code": response.status_code}},
            )
            return CommunicationResult(status="failed", error_code=f"twilio_status_{response.status_code}")

        provider_msg_id = None
        try:
            payload = response.json()
            provider_msg_id = payload.get("sid")
        except Exception:  # noqa: BLE001
            logger.warning("twilio_response_parse_failed")
        return CommunicationResult(status="sent", provider_msg_id=provider_msg_id)


def resolve_communication_adapter(app_settings) -> TwilioCommunicationAdapter | NoopCommunicationAdapter:
    if app_settings.sms_mode != "twilio" and app_settings.call_mode != "twilio":
        return NoopCommunicationAdapter()
    return TwilioCommunicationAdapter()


def resolve_app_communication_adapter(app_like) -> TwilioCommunicationAdapter | NoopCommunicationAdapter | None:
    state = getattr(app_like, "state", None)
    if state is None:
        return None
    app_state = getattr(getattr(app_like, "app", None), "state", None) or state
    adapter = getattr(app_state, "communication_adapter", None)
    if adapter is not None:
        return adapter
    services = getattr(app_state, "services", None)
    if services is not None:
        return getattr(services, "communication_adapter", None)
    return None


def _twilio_sms_configured() -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_sms_from)


def _twilio_call_configured() -> bool:
    return bool(
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_call_from
        and settings.twilio_call_url
    )


def _twilio_messages_url() -> str:
    return f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"


def _twilio_calls_url() -> str:
    return f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Calls.json"
