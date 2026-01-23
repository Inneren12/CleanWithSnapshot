from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import InMemorySpanExporter, SimpleSpanProcessor
from opentelemetry.trace import SpanKind

from app import main
from app.settings import settings


def test_request_id_attached_to_server_span(monkeypatch):
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    def _configure_tracing(*args, **kwargs) -> None:
        trace.set_tracer_provider(tracer_provider)

    monkeypatch.setattr(main, "configure_tracing", _configure_tracing)

    app = main.create_app(settings)
    with TestClient(app) as client:
        response = client.get("/healthz")

    request_id = response.headers.get("X-Request-ID")
    spans = exporter.get_finished_spans()
    server_spans = [span for span in spans if span.kind is SpanKind.SERVER]

    assert request_id
    assert server_spans
    assert any(span.attributes.get("request_id") == request_id for span in server_spans)
