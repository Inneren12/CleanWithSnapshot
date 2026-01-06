import socket
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.ops.db_models import JobHeartbeat
from app.infra.metrics import metrics


def _resolve_runner_id(runner_id: str | None = None) -> str:
    if runner_id and runner_id.strip():
        return runner_id.strip()
    return socket.gethostname()


async def record_heartbeat(
    session_factory: async_sessionmaker, name: str = "jobs-runner", *, runner_id: str | None = None
) -> None:
    now = datetime.now(tz=timezone.utc)
    resolved_runner_id = _resolve_runner_id(runner_id)
    async with session_factory() as session:
        heartbeat = await session.get(JobHeartbeat, name)
        if heartbeat is None:
            heartbeat = JobHeartbeat(
                name=name,
                last_heartbeat=now,
                last_success_at=now,
                runner_id=resolved_runner_id,
                consecutive_failures=0,
                updated_at=now,
            )
            session.add(heartbeat)
        else:
            heartbeat.last_heartbeat = now
            heartbeat.last_success_at = now
            heartbeat.runner_id = resolved_runner_id
            heartbeat.consecutive_failures = 0
            heartbeat.last_error = None
            heartbeat.last_error_at = None
        await session.commit()
    metrics.record_job_heartbeat(name, now.timestamp())
    metrics.record_job_success(name, now.timestamp())
