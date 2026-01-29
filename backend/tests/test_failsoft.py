from datetime import datetime, timedelta, timezone

from app.settings import settings


def _create_lead(client) -> str:
    estimate_response = client.post(
        "/v1/estimate",
        json={
            "beds": 1,
            "baths": 1,
            "cleaning_type": "standard",
            "heavy_grease": False,
            "multi_floor": False,
            "frequency": "one_time",
            "add_ons": {},
        },
    )
    assert estimate_response.status_code == 200
    payload = {
        "name": "Failsoft Lead",
        "phone": "780-555-0000",
        "address": "11 Failsoft Street",
        "preferred_dates": ["Mon morning"],
        "structured_inputs": {"beds": 1, "baths": 1, "cleaning_type": "standard"},
        "estimate_snapshot": estimate_response.json(),
    }
    response = client.post("/v1/leads", json=payload)
    assert response.status_code == 201
    return response.json()["lead_id"]


def test_booking_succeeds_when_email_fails(client, monkeypatch):
    future_start = (datetime.now(tz=timezone.utc) + timedelta(days=5)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )

    async def _boom(*_: object, **__: object):  # pragma: no cover - exercised via request
        raise RuntimeError("email_down")

    monkeypatch.setattr("app.domain.notifications.email_service.send_booking_pending_email", _boom)

    slots = client.get(
        "/v1/slots", params={"date": future_start.date().isoformat(), "time_on_site_hours": 1.5}
    )
    assert slots.status_code == 200
    chosen = slots.json()["slots"][0]

    lead_id = _create_lead(client)
    response = client.post(
        "/v1/bookings",
        json={"starts_at": chosen, "time_on_site_hours": 1.5, "lead_id": lead_id},
    )

    assert response.status_code == 201, response.text


def test_metrics_endpoint_returns_empty_when_disabled(admin_client):
    settings.metrics_enabled = False
    response = admin_client.get("/v1/admin/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["conversions"] == {
        "lead_created": 0,
        "booking_created": 0,
        "booking_confirmed": 0,
        "job_completed": 0,
    }
    assert body["accuracy"]["sample_size"] == 0


def test_auth_failure_returns_401_not_503(anon_client_no_raise):
    response = anon_client_no_raise.get("/v1/admin/leads")
    assert response.status_code == 401
