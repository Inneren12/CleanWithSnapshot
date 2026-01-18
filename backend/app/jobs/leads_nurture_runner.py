from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.leads_nurture import runner as nurture_runner
from app.infra.communication import NoopCommunicationAdapter, TwilioCommunicationAdapter
from app.infra.email import EmailAdapter, NoopEmailAdapter


async def run_leads_nurture_runner(
    session: AsyncSession,
    email_adapter: EmailAdapter | NoopEmailAdapter | None,
    communication_adapter: TwilioCommunicationAdapter | NoopCommunicationAdapter | None,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    return await nurture_runner.run_leads_nurture_runner(
        session,
        email_adapter,
        communication_adapter,
        now=now or datetime.now(tz=timezone.utc),
    )
