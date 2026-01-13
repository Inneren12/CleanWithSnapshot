from datetime import datetime, timedelta, timezone

from httpx import MockTransport, Response

from app.main import app
from app.domain.bookings.service import LOCAL_TZ
from app.settings import settings


def _lead_payload(client):
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
    estimate = estimate_response.json()

    return {
        "name": "Captcha Test",
        "phone": "780-555-0000",
        "email": "captcha@example.com",
        "address": "404 Captcha Lane",
        "preferred_dates": ["Sat morning"],
        "structured_inputs": {"beds": 1, "baths": 1, "cleaning_type": "standard"},
        "estimate_snapshot": estimate,
    }


def _booking_payload(lead_id: str):
    now_local = datetime.now(tz=LOCAL_TZ)
    target_local = (now_local + timedelta(days=5)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    starts_at = target_local.astimezone(timezone.utc).isoformat()
    return {"starts_at": starts_at, "time_on_site_hours": 2, "lead_id": lead_id}


def _create_lead(client) -> str:
    response = client.post("/v1/leads", json=_lead_payload(client))
    assert response.status_code == 201
    return response.json()["lead_id"]


def test_leads_captcha_off_allows(client):
    original_mode = settings.captcha_mode
    original_secret = settings.turnstile_secret_key
    original_transport = getattr(app.state, "turnstile_transport", None)

    settings.captcha_mode = "off"
    settings.turnstile_secret_key = None
    app.state.turnstile_transport = None

    try:
        response = client.post("/v1/leads", json=_lead_payload(client))
        assert response.status_code == 201
    finally:
        settings.captcha_mode = original_mode
        settings.turnstile_secret_key = original_secret
        app.state.turnstile_transport = original_transport


def test_leads_captcha_turnstile_requires_token(client):
    original_mode = settings.captcha_mode
    original_secret = settings.turnstile_secret_key
    original_transport = getattr(app.state, "turnstile_transport", None)
    original_enabled = settings.captcha_enabled

    settings.captcha_mode = "turnstile"
    settings.turnstile_secret_key = "secret-key"
    settings.captcha_enabled = True
    app.state.turnstile_transport = None

    try:
        response = client.post("/v1/leads", json=_lead_payload(client))
        assert response.status_code == 422
    finally:
        settings.captcha_mode = original_mode
        settings.turnstile_secret_key = original_secret
        settings.captcha_enabled = original_enabled
        app.state.turnstile_transport = original_transport


def test_leads_captcha_turnstile_accepts_valid_token(client):
    original_mode = settings.captcha_mode
    original_secret = settings.turnstile_secret_key
    original_transport = getattr(app.state, "turnstile_transport", None)
    original_enabled = settings.captcha_enabled

    settings.captcha_mode = "turnstile"
    settings.turnstile_secret_key = "secret-key"
    settings.captcha_enabled = True
    app.state.turnstile_transport = MockTransport(
        lambda request: Response(200, request=request, json={"success": True})
    )

    lead_payload = _lead_payload(client)
    lead_payload["captcha_token"] = "ok"

    try:
        response = client.post("/v1/leads", json=lead_payload)
        assert response.status_code == 201
    finally:
        settings.captcha_mode = original_mode
        settings.turnstile_secret_key = original_secret
        settings.captcha_enabled = original_enabled
        app.state.turnstile_transport = original_transport


def test_leads_captcha_turnstile_rejects_invalid_token(client):
    original_mode = settings.captcha_mode
    original_secret = settings.turnstile_secret_key
    original_transport = getattr(app.state, "turnstile_transport", None)
    original_enabled = settings.captcha_enabled

    settings.captcha_mode = "turnstile"
    settings.turnstile_secret_key = "secret-key"
    settings.captcha_enabled = True
    app.state.turnstile_transport = MockTransport(
        lambda request: Response(200, request=request, json={"success": False})
    )

    lead_payload = _lead_payload(client)
    lead_payload["captcha_token"] = "bad"

    try:
        response = client.post("/v1/leads", json=lead_payload)
        assert response.status_code == 400
    finally:
        settings.captcha_mode = original_mode
        settings.turnstile_secret_key = original_secret
        settings.captcha_enabled = original_enabled
        app.state.turnstile_transport = original_transport


def test_bookings_captcha_prod_missing_token_blocks(client):
    original_mode = settings.captcha_mode
    original_secret = settings.turnstile_secret_key
    original_transport = getattr(app.state, "turnstile_transport", None)
    original_env = settings.app_env
    original_enabled = settings.captcha_enabled
    lead_id = _create_lead(client)

    settings.app_env = "prod"
    settings.captcha_enabled = True
    settings.captcha_mode = "turnstile"
    settings.turnstile_secret_key = "secret-key"
    app.state.turnstile_transport = None

    try:
        response = client.post("/v1/bookings", json=_booking_payload(lead_id))
        assert response.status_code == 422
    finally:
        settings.app_env = original_env
        settings.captcha_enabled = original_enabled
        settings.captcha_mode = original_mode
        settings.turnstile_secret_key = original_secret
        app.state.turnstile_transport = original_transport


def test_bookings_captcha_prod_invalid_token_blocks(client):
    original_mode = settings.captcha_mode
    original_secret = settings.turnstile_secret_key
    original_transport = getattr(app.state, "turnstile_transport", None)
    original_env = settings.app_env
    original_enabled = settings.captcha_enabled
    lead_id = _create_lead(client)

    settings.app_env = "prod"
    settings.captcha_enabled = True
    settings.captcha_mode = "turnstile"
    settings.turnstile_secret_key = "secret-key"
    app.state.turnstile_transport = MockTransport(
        lambda request: Response(200, request=request, json={"success": False})
    )

    payload = _booking_payload(lead_id)
    payload["captcha_token"] = "bad"

    try:
        response = client.post("/v1/bookings", json=payload)
        assert response.status_code == 400
    finally:
        settings.app_env = original_env
        settings.captcha_enabled = original_enabled
        settings.captcha_mode = original_mode
        settings.turnstile_secret_key = original_secret
        app.state.turnstile_transport = original_transport


def test_bookings_captcha_dev_bypass_allows(client):
    original_mode = settings.captcha_mode
    original_secret = settings.turnstile_secret_key
    original_transport = getattr(app.state, "turnstile_transport", None)
    original_env = settings.app_env
    original_enabled = settings.captcha_enabled
    lead_id = _create_lead(client)

    settings.app_env = "dev"
    settings.captcha_enabled = False
    settings.captcha_mode = "turnstile"
    settings.turnstile_secret_key = None
    app.state.turnstile_transport = None

    try:
        response = client.post("/v1/bookings", json=_booking_payload(lead_id))
        assert response.status_code == 201
    finally:
        settings.app_env = original_env
        settings.captcha_enabled = original_enabled
        settings.captcha_mode = original_mode
        settings.turnstile_secret_key = original_secret
        app.state.turnstile_transport = original_transport


def test_bookings_captcha_testing_bypass_allows(client):
    original_mode = settings.captcha_mode
    original_secret = settings.turnstile_secret_key
    original_transport = getattr(app.state, "turnstile_transport", None)
    original_enabled = settings.captcha_enabled
    original_testing = settings.testing
    lead_id = _create_lead(client)

    settings.testing = True
    settings.captcha_enabled = False
    settings.captcha_mode = "turnstile"
    settings.turnstile_secret_key = None
    app.state.turnstile_transport = None

    try:
        response = client.post("/v1/bookings", json=_booking_payload(lead_id))
        assert response.status_code == 201
    finally:
        settings.testing = original_testing
        settings.captcha_enabled = original_enabled
        settings.captcha_mode = original_mode
        settings.turnstile_secret_key = original_secret
        app.state.turnstile_transport = original_transport
