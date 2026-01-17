from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications_digests import service as digest_service
from app.infra.email import EmailAdapter, NoopEmailAdapter


async def run_notifications_digest(
    session: AsyncSession,
    adapter: EmailAdapter | NoopEmailAdapter | None,
    *,
    schedule: str,
    now: datetime | None = None,
) -> dict[str, int]:
    return await digest_service.run_digest_delivery(
        session,
        adapter,
        schedule=schedule,
        now=now or datetime.now(tz=timezone.utc),
    )
