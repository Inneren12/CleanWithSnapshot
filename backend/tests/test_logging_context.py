import logging

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import settings


def test_unhandled_exception_logs_request_id(caplog):
    app = create_app(settings)

    @app.get("/_test/boom")
    async def boom():  # pragma: no cover - executed in test client
        raise RuntimeError("boom")

    caplog.set_level(logging.ERROR)
    with TestClient(app) as client:
        response = client.get("/_test/boom")

    assert response.status_code == 500
    error_records = [record for record in caplog.records if record.message == "unhandled_exception"]
    assert error_records
    assert getattr(error_records[0], "request_id", None)
