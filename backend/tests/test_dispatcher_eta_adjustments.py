from datetime import datetime, timezone

from app.domain.dispatcher import service as dispatcher_service
from app.settings import settings


def test_winter_multiplier_applies(monkeypatch):
    monkeypatch.setattr(settings, "dispatcher_winter_months", [12])
    monkeypatch.setattr(settings, "dispatcher_winter_travel_multiplier", 1.1)
    monkeypatch.setattr(settings, "dispatcher_winter_buffer_min", 0)
    monkeypatch.setattr(settings, "dispatcher_downtown_parking_buffer_min", 0)
    adjusted, adjustments = dispatcher_service.apply_eta_adjustments(
        base_duration_min=30,
        depart_at=datetime(2024, 12, 15, 18, 0, tzinfo=timezone.utc),
        zone=None,
        lat=None,
        lng=None,
    )

    assert adjusted == 33
    assert any(adjustment.code == "winter_travel_multiplier" for adjustment in adjustments)


def test_downtown_buffer_applies(monkeypatch):
    monkeypatch.setattr(settings, "dispatcher_winter_months", [])
    monkeypatch.setattr(settings, "dispatcher_downtown_parking_buffer_min", 15)
    adjusted, adjustments = dispatcher_service.apply_eta_adjustments(
        base_duration_min=20,
        depart_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        zone="Downtown",
        lat=53.5461,
        lng=-113.4938,
    )

    assert adjusted == 35
    assert any(adjustment.code == "downtown_parking_buffer" for adjustment in adjustments)


def test_non_winter_month_has_no_adjustments(monkeypatch):
    monkeypatch.setattr(settings, "dispatcher_winter_months", [12])
    monkeypatch.setattr(settings, "dispatcher_downtown_parking_buffer_min", 15)
    adjusted, adjustments = dispatcher_service.apply_eta_adjustments(
        base_duration_min=25,
        depart_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        zone="West",
        lat=0.0,
        lng=0.0,
    )

    assert adjusted == 25
    assert adjustments == []
