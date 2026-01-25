import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import entitlements
from app.domain.saas import billing_service, service as saas_service
from app.domain.saas.plans import Plan, PlanLimits
from app.infra.metrics import metrics


def _counter_value(counter, **labels) -> float:
    if labels:
        return counter.labels(**labels)._value.get()
    return counter._value.get()


@pytest.mark.anyio
async def test_booking_quota_rejection_emits_metric(async_session_maker, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Booking Quota Org")
        await billing_service.set_plan(session, org.org_id, plan_id="free", status="active")
        await session.commit()

    limited_plan = Plan(
        plan_id="limited",
        name="Limited",
        price_cents=0,
        currency="usd",
        stripe_price_id=None,
        limits=PlanLimits(max_workers=1, max_bookings_per_month=0, storage_gb=1),
    )

    async def _fake_plan(session, org_id):
        return limited_plan

    monkeypatch.setattr(billing_service, "get_current_plan", _fake_plan)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/bookings",
            "headers": [],
        }
    )
    request.state.saas_identity = object()
    request.state.current_org_id = org.org_id
    request.state.request_id = "req-booking-quota"

    baseline = _counter_value(metrics.org_active_bookings_quota_rejections, reason="monthly_limit")

    async with async_session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await entitlements.require_booking_entitlement(request, session=session)

    assert exc.value.status_code == 402
    assert (
        _counter_value(metrics.org_active_bookings_quota_rejections, reason="monthly_limit")
        == baseline + 1
    )
