from app.infra import tracing


def test_otlp_exporter_disabled_by_default_in_ci(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENABLED", raising=False)
    assert tracing._should_enable_otlp_exporter("ci", testing=False) is False


def test_otlp_exporter_enabled_when_flag_set(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENABLED", "true")
    assert tracing._should_enable_otlp_exporter("ci", testing=False) is True


def test_otlp_exporter_disabled_when_testing(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENABLED", "true")
    assert tracing._should_enable_otlp_exporter("prod", testing=True) is False
