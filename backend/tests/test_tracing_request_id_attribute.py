from importlib.util import find_spec

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import SpanKind

if find_spec("opentelemetry.sdk.trace.export.in_memory_span_exporter"):
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
else:  # pragma: no cover - compatibility with older OTel versions
    from opentelemetry.sdk.trace.export import InMemorySpanExporter

from app import main
from app.settings import settings


def test_request_id_attached_to_server_span():
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    app = main.create_app(settings, tracer_provider=tracer_provider)
    with TestClient(app) as client:
        response = client.get("/healthz")

    if hasattr(tracer_provider, "force_flush"):
        tracer_provider.force_flush()

    request_id = response.headers.get("X-Request-ID")
    spans = exporter.get_finished_spans()
    server_spans = [span for span in spans if span.kind is SpanKind.SERVER]

    assert request_id
    assert server_spans
    assert any(span.attributes.get("request_id") == request_id for span in server_spans)
