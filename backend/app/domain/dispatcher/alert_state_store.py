from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

import redis.asyncio as redis
from redis.exceptions import RedisError
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dispatcher.db_models import DispatcherAlertState
from app.settings import settings

logger = logging.getLogger(__name__)

_REDIS_CLIENT: redis.Redis | None = None


class AlertStateStore(Protocol):
    async def is_acked(self, org_id: uuid.UUID, alert_key: str, now: datetime) -> bool:
        ...

    async def ack(self, org_id: uuid.UUID, alert_key: str, until: datetime) -> None:
        ...

    async def allow_sms_send(
        self, org_id: uuid.UUID, alert_key: str, now: datetime, ttl: timedelta
    ) -> bool:
        ...


def _redis_key(namespace: str, org_id: uuid.UUID, alert_key: str) -> str:
    return f"dispatcher:alerts:{org_id}:{namespace}:{alert_key}"


async def _redis_client() -> redis.Redis | None:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT
    if not settings.redis_url:
        return None
    _REDIS_CLIENT = redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=False)
    return _REDIS_CLIENT


def _seconds_until(until: datetime, now: datetime) -> int:
    return max(int((until - now).total_seconds()), 1)


class RedisAlertStateStore:
    async def is_acked(self, org_id: uuid.UUID, alert_key: str, now: datetime) -> bool:
        client = await _redis_client()
        if client is None:
            return False
        key = _redis_key("ack", org_id, alert_key)
        try:
            return await client.get(key) is not None
        except RedisError:
            logger.warning("dispatcher_alert_redis_failed", extra={"extra": {"op": "get_ack"}})
            return False

    async def ack(self, org_id: uuid.UUID, alert_key: str, until: datetime) -> None:
        client = await _redis_client()
        if client is None:
            return
        key = _redis_key("ack", org_id, alert_key)
        now = datetime.now(timezone.utc)
        ttl_seconds = _seconds_until(until, now)
        try:
            await client.set(key, "1", ex=ttl_seconds)
        except RedisError:
            logger.warning("dispatcher_alert_redis_failed", extra={"extra": {"op": "set_ack"}})

    async def allow_sms_send(
        self, org_id: uuid.UUID, alert_key: str, now: datetime, ttl: timedelta
    ) -> bool:
        client = await _redis_client()
        if client is None:
            return True
        key = _redis_key("sms", org_id, alert_key)
        ttl_seconds = max(int(ttl.total_seconds()), 1)
        try:
            result = await client.set(key, "1", ex=ttl_seconds, nx=True)
            return result is True
        except RedisError:
            logger.warning("dispatcher_alert_redis_failed", extra={"extra": {"op": "set_sms"}})
            return True


class DbAlertStateStore:
    async def is_acked(self, org_id: uuid.UUID, alert_key: str, now: datetime) -> bool:
        stmt = select(DispatcherAlertState.acked_until).where(
            DispatcherAlertState.org_id == org_id,
            DispatcherAlertState.alert_key == alert_key,
        )
        result = await self._session.scalar(stmt)
        if result and result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return bool(result and result > now)

    async def ack(self, org_id: uuid.UUID, alert_key: str, until: datetime) -> None:
        stmt = _insert_statement(self._session).values(
            org_id=org_id,
            alert_key=alert_key,
            acked_until=until,
        )
        upsert = stmt.on_conflict_do_update(
            index_elements=[DispatcherAlertState.org_id, DispatcherAlertState.alert_key],
            set_={
                "acked_until": sa.case(
                    (
                        sa.or_(
                            DispatcherAlertState.acked_until.is_(None),
                            DispatcherAlertState.acked_until < until,
                        ),
                        until,
                    ),
                    else_=DispatcherAlertState.acked_until,
                ),
                "updated_at": sa.func.now(),
            },
        )
        await self._session.execute(upsert)
        await self._session.commit()

    async def allow_sms_send(
        self, org_id: uuid.UUID, alert_key: str, now: datetime, ttl: timedelta
    ) -> bool:
        until = now + ttl
        stmt = _insert_statement(self._session).values(
            org_id=org_id,
            alert_key=alert_key,
            sms_throttle_until=until,
        )
        upsert = stmt.on_conflict_do_update(
            index_elements=[DispatcherAlertState.org_id, DispatcherAlertState.alert_key],
            set_={
                "sms_throttle_until": until,
                "updated_at": sa.func.now(),
            },
            where=sa.or_(
                DispatcherAlertState.sms_throttle_until.is_(None),
                DispatcherAlertState.sms_throttle_until <= now,
            ),
        ).returning(DispatcherAlertState.alert_key)
        result = await self._session.execute(upsert)
        allowed = result.first() is not None
        if allowed:
            await self._session.commit()
        return allowed

    def __init__(self, session: AsyncSession) -> None:
        self._session = session


def _insert_statement(session: AsyncSession):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        return insert(DispatcherAlertState)
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert

        return insert(DispatcherAlertState)
    return sa.insert(DispatcherAlertState)


def get_alert_state_store(session: AsyncSession) -> AlertStateStore:
    if settings.redis_url:
        return RedisAlertStateStore()
    return DbAlertStateStore(session)
