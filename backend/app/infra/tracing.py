import atexit
import logging
import os
import subprocess
from pathlib import Path

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT, SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_TRACING_CONFIGURED = False
_HTTPX_CONFIGURED = False
_SQLALCHEMY_ENGINES: set[int] = set()
_TRACING_SHUTDOWN = False
_TRACING_SHUTDOWN_REGISTERED = False

logger = logging.getLogger(__name__)


def _resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_service_version() -> str | None:
    for key in ("GIT_SHA", "GIT_COMMIT", "SOURCE_VERSION", "SERVICE_VERSION"):
        value = os.getenv(key)
        if value:
            return value
    git_dir = _resolve_repo_root()
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=git_dir, text=True).strip()
    except Exception:
        return None
    return sha or None


def _sanitize_http_attributes(span, *, path: str | None, scheme: str | None, host: str | None) -> None:
    if not span or not span.is_recording():
        return
    sanitized_path = path or "/"
    if scheme and host:
        span.set_attribute("http.url", f"{scheme}://{host}{sanitized_path}")
    span.set_attribute("http.target", sanitized_path)


def _fastapi_request_hook(span, scope) -> None:  # noqa: ANN001
    server = scope.get("server") or (None, None)
    host = server[0] if server else None
    route = scope.get("route")
    route_path = getattr(route, "path", None)
    _sanitize_http_attributes(
        span,
        path=route_path or scope.get("path", "/"),
        scheme=scope.get("scheme"),
        host=host,
    )


def _httpx_request_hook(span, request) -> None:  # noqa: ANN001
    url = request.url
    sanitized_url = url.copy_with(query=None)
    _sanitize_http_attributes(
        span,
        path=sanitized_url.path,
        scheme=sanitized_url.scheme,
        host=sanitized_url.host,
    )


def configure_tracing(*, service_name: str | None = None) -> None:
    global _TRACING_CONFIGURED, _HTTPX_CONFIGURED, _TRACING_SHUTDOWN_REGISTERED
    if _TRACING_CONFIGURED:
        return

    resolved_service_name = os.getenv("OTEL_SERVICE_NAME") or service_name or "api"
    deployment_env = os.getenv("DEPLOYMENT_ENV", "local")
    service_version = _resolve_service_version()

    resource_attrs = {
        SERVICE_NAME: resolved_service_name,
        DEPLOYMENT_ENVIRONMENT: deployment_env,
    }
    if service_version:
        resource_attrs[SERVICE_VERSION] = service_version

    resource = Resource.create(resource_attrs)
    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    app_env = os.getenv("APP_ENV", "").lower()
    is_testing = os.getenv("TESTING", "").lower() == "true" or app_env == "test"
    if otlp_endpoint and not is_testing:
        exporter_kwargs: dict[str, object] = {
            "endpoint": otlp_endpoint,
            "insecure": otlp_endpoint.startswith("http://"),
        }
        exporter = OTLPSpanExporter(**exporter_kwargs)
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    elif not otlp_endpoint and not is_testing:
        logger.debug("tracing_exporter_skipped_no_endpoint")

    if not _HTTPX_CONFIGURED:
        HTTPXClientInstrumentor().instrument(
            tracer_provider=tracer_provider,
            request_hook=_httpx_request_hook,
        )
        _HTTPX_CONFIGURED = True

    _TRACING_CONFIGURED = True

    if not _TRACING_SHUTDOWN_REGISTERED:
        atexit.register(shutdown_tracing)
        _TRACING_SHUTDOWN_REGISTERED = True


def instrument_fastapi(app: FastAPI, *, tracer_provider=None) -> None:  # noqa: ANN001
    FastAPIInstrumentor().instrument_app(
        app,
        tracer_provider=tracer_provider or trace.get_tracer_provider(),
        server_request_hook=_fastapi_request_hook,
    )


def instrument_sqlalchemy(engine) -> None:  # noqa: ANN001
    if engine is None:
        return
    engine_id = id(engine)
    if engine_id in _SQLALCHEMY_ENGINES:
        return
    SQLAlchemyInstrumentor().instrument(
        engine=engine,
        tracer_provider=trace.get_tracer_provider(),
        capture_statement=False,
    )
    _SQLALCHEMY_ENGINES.add(engine_id)


def shutdown_tracing(*, force_flush: bool = True) -> None:
    global _TRACING_SHUTDOWN
    if _TRACING_SHUTDOWN:
        return
    _TRACING_SHUTDOWN = True
    try:
        tracer_provider = trace.get_tracer_provider()
        if force_flush:
            flush = getattr(tracer_provider, "force_flush", None)
            if callable(flush):
                flush()
        shutdown = getattr(tracer_provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
    except Exception as exc:  # noqa: BLE001
        logger.warning("tracing_shutdown_failed", extra={"extra": {"error": type(exc).__name__}})
