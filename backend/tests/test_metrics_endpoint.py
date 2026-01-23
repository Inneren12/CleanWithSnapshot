from app.infra.metrics import configure_metrics, metrics
from app.main import app
from app.settings import settings


def test_metrics_endpoint_requires_token_when_configured(client):
    settings.metrics_token = "secret-token"
    settings.app_env = "prod"
    settings.metrics_enabled = True
    app.state.metrics = configure_metrics(True, service_name=settings.app_name)

    unauthorized = client.get("/metrics")
    assert unauthorized.status_code == 401

    authorized = client.get("/metrics", headers={"Authorization": "Bearer secret-token"})
    assert authorized.status_code == 200

    query_token = client.get("/metrics?token=secret-token")
    assert query_token.status_code == 200


def test_metrics_path_label_uses_route_template(client_no_raise):
    settings.metrics_token = None
    settings.app_env = "dev"
    configure_metrics(True, service_name=settings.app_name)

    async def boom_handler(item_id: str):  # pragma: no cover - handler executed in request
        raise RuntimeError("boom")

    app.router.add_api_route("/boom/{item_id}", boom_handler, methods=["GET"])

    response = client_no_raise.get("/boom/123")
    assert response.status_code == 500

    samples = []
    for metric in app.state.metrics.http_5xx.collect():
        samples.extend(metric.samples)

    assert any(sample.labels.get("route") == "/boom/{item_id}" for sample in samples)

    app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != "/boom/{item_id}"]


def test_metrics_unmatched_path_uses_placeholder(client_no_raise):
    settings.metrics_token = None
    settings.app_env = "dev"
    configure_metrics(True, service_name=settings.app_name)

    response = client_no_raise.get("/does-not-exist/12345/abc")
    assert response.status_code == 404

    samples = []
    for metric in app.state.metrics.http_latency.collect():
        samples.extend(metric.samples)

    assert any(sample.labels.get("route") == "unmatched" for sample in samples)


def test_metrics_endpoint_disabled_when_metrics_off(client):
    settings.metrics_enabled = False
    settings.metrics_token = None
    if hasattr(app.state, "metrics"):
        delattr(app.state, "metrics")

    response = client.get("/metrics")

    assert response.status_code == 404


def test_metrics_endpoint_exports_http_series(client):
    settings.metrics_enabled = True
    settings.metrics_token = None
    settings.app_env = "dev"
    settings.app_name = "test-service"
    app.state.metrics = configure_metrics(True, service_name=settings.app_name)

    response = client.get("/healthz")
    assert response.status_code == 200

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    payload = metrics_response.text

    assert "http_requests_total" in payload
    assert "http_request_latency_seconds_bucket" in payload
    assert 'route="/healthz"' in payload
    assert 'service="test-service"' in payload


def test_metrics_endpoint_exports_jobs_and_outbox_series(client):
    settings.metrics_enabled = True
    settings.metrics_token = None
    settings.app_env = "dev"
    settings.app_name = "test-service"
    app.state.metrics = configure_metrics(True, service_name=settings.app_name)

    metrics.record_job_success("outbox-delivery", 1728000000.0)
    metrics.record_job_run("outbox-delivery", "success")
    metrics.record_job_duration("outbox-delivery", 1.25)
    metrics.set_outbox_pending_total("email", 2)
    metrics.record_outbox_delivery("email", "success")
    metrics.set_outbox_lag("email", 12.5)

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    payload = metrics_response.text

    assert "jobs_last_success_timestamp" in payload
    assert "jobs_run_total" in payload
    assert "jobs_duration_seconds_bucket" in payload
    assert "outbox_pending_total" in payload
    assert "outbox_deliver_total" in payload
    assert "outbox_lag_seconds" in payload
