import anyio

from app.infra import tracing as tracing_module
from app.jobs import run as jobs_run


def test_jobs_runner_shutdowns_tracing(monkeypatch):
    class FakeTracerProvider:
        def __init__(self) -> None:
            self.force_flush_called = 0
            self.shutdown_called = 0

        def force_flush(self) -> None:
            self.force_flush_called += 1

        def shutdown(self) -> None:
            self.shutdown_called += 1

    fake_provider = FakeTracerProvider()

    monkeypatch.setattr(tracing_module.trace, "get_tracer_provider", lambda: fake_provider)
    monkeypatch.setattr(jobs_run, "configure_tracing", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobs_run, "resolve_email_adapter", lambda *args, **kwargs: object())
    monkeypatch.setattr(jobs_run, "new_storage_backend", lambda *args, **kwargs: object())
    monkeypatch.setattr(jobs_run, "resolve_communication_adapter", lambda *args, **kwargs: object())
    monkeypatch.setattr(jobs_run, "configure_metrics", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobs_run, "get_session_factory", lambda *args, **kwargs: object())

    async def noop_run_job(*args, **kwargs) -> None:
        return None

    async def noop_async(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(jobs_run, "_run_job", noop_run_job)
    monkeypatch.setattr(jobs_run, "record_heartbeat", noop_async)
    monkeypatch.setattr(jobs_run, "_notify_external_heartbeat", noop_async)

    tracing_module._TRACING_SHUTDOWN = False

    anyio.run(jobs_run.run, ["--once", "--job", "booking-reminders"])

    assert fake_provider.force_flush_called == 1
    assert fake_provider.shutdown_called == 1
