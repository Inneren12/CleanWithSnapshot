"""Tests for competitor benchmarking analytics endpoints."""

from __future__ import annotations

from datetime import date
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feature_modules.db_models import OrgFeatureConfig
from app.domain.saas.db_models import Organization
from app.main import app
from app.settings import settings

ADMIN_HEADERS = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}  # admin:admin123


@pytest.fixture
async def orgs(db_session: AsyncSession) -> tuple[Organization, Organization]:
    org_id = settings.default_org_id
    org_a = await db_session.get(Organization, org_id)
    if org_a is None:
        org_a = Organization(org_id=org_id, name="Competitor Org A")
        db_session.add(org_a)
    else:
        org_a.name = "Competitor Org A"

    org_b = Organization(org_id=uuid.uuid4(), name="Competitor Org B")
    db_session.add(org_b)

    await db_session.commit()

    for org in (org_a, org_b):
        config = await db_session.get(OrgFeatureConfig, org.org_id)
        if config is None:
            config = OrgFeatureConfig(org_id=org.org_id, feature_overrides={})
            db_session.add(config)
        config.feature_overrides = {"analytics.competitors": True}
    await db_session.commit()
    return org_a, org_b


@pytest.mark.anyio
async def test_competitor_crud_org_scoping(
    client: TestClient, orgs: tuple[Organization, Organization]
):
    org_a, org_b = orgs

    create_resp = client.post(
        "/v1/admin/analytics/competitors",
        headers=ADMIN_HEADERS,
        json={"name": "Sparkle Clean", "platform": "Google", "profile_url": "https://example.com"},
    )
    assert create_resp.status_code == 201
    competitor_id = create_resp.json()["competitor_id"]

    list_resp = client.get("/v1/admin/analytics/competitors", headers=ADMIN_HEADERS)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    org_b_headers = {**ADMIN_HEADERS, "X-Test-Org": str(org_b.org_id)}
    create_other = client.post(
        "/v1/admin/analytics/competitors",
        headers=org_b_headers,
        json={"name": "Tidy Co", "platform": "Yelp"},
    )
    assert create_other.status_code == 201

    list_other = client.get("/v1/admin/analytics/competitors", headers=org_b_headers)
    assert list_other.status_code == 200
    assert len(list_other.json()) == 1

    list_again = client.get("/v1/admin/analytics/competitors", headers=ADMIN_HEADERS)
    assert len(list_again.json()) == 1

    wrong_org_get = client.get(
        f"/v1/admin/analytics/competitors/{competitor_id}", headers=org_b_headers
    )
    assert wrong_org_get.status_code == 404

    wrong_org_update = client.patch(
        f"/v1/admin/analytics/competitors/{competitor_id}",
        headers=org_b_headers,
        json={"name": "Nope"},
    )
    assert wrong_org_update.status_code == 404


@pytest.mark.anyio
async def test_metrics_crud_and_benchmark(
    client: TestClient, orgs: tuple[Organization, Organization]
):
    org_a, _org_b = orgs

    create_resp = client.post(
        "/v1/admin/analytics/competitors",
        headers=ADMIN_HEADERS,
        json={"name": "Clean Stars", "platform": "Google"},
    )
    competitor_id = create_resp.json()["competitor_id"]

    metric_one = client.post(
        f"/v1/admin/analytics/competitors/{competitor_id}/metrics",
        headers=ADMIN_HEADERS,
        json={
            "as_of_date": "2026-01-10",
            "rating": 4.5,
            "review_count": 120,
            "avg_response_hours": 2.0,
        },
    )
    assert metric_one.status_code == 201
    metric_id = metric_one.json()["metric_id"]

    metric_two = client.post(
        f"/v1/admin/analytics/competitors/{competitor_id}/metrics",
        headers=ADMIN_HEADERS,
        json={
            "as_of_date": "2026-01-15",
            "rating": 5.0,
            "review_count": 150,
            "avg_response_hours": 4.0,
        },
    )
    assert metric_two.status_code == 201

    list_metrics = client.get(
        f"/v1/admin/analytics/competitors/{competitor_id}/metrics",
        headers=ADMIN_HEADERS,
    )
    assert list_metrics.status_code == 200
    assert len(list_metrics.json()) == 2

    update_metric = client.patch(
        f"/v1/admin/analytics/competitors/{competitor_id}/metrics/{metric_id}",
        headers=ADMIN_HEADERS,
        json={"rating": 4.8},
    )
    assert update_metric.status_code == 200
    assert update_metric.json()["rating"] == 4.8

    benchmark = client.get(
        "/v1/admin/analytics/competitors/benchmark?from=2026-01-01&to=2026-01-31",
        headers=ADMIN_HEADERS,
    )
    assert benchmark.status_code == 200
    payload = benchmark.json()
    assert payload["range_start"] == str(date(2026, 1, 1))
    assert payload["range_end"] == str(date(2026, 1, 31))
    assert len(payload["items"]) == 1
    entry = payload["items"][0]
    assert entry["sample_count"] == 2
    assert entry["avg_rating"] == pytest.approx(4.9, rel=1e-3)
    assert entry["max_review_count"] == 150
    assert entry["avg_response_hours"] == pytest.approx(3.0, rel=1e-3)

    delete_metric = client.delete(
        f"/v1/admin/analytics/competitors/{competitor_id}/metrics/{metric_id}",
        headers=ADMIN_HEADERS,
    )
    assert delete_metric.status_code == 204


@pytest.mark.anyio
async def test_competitors_feature_flag_blocks_access(
    client: TestClient, db_session: AsyncSession
):
    org_id = settings.default_org_id
    org = await db_session.get(Organization, org_id)
    if org is None:
        org = Organization(org_id=org_id, name="Competitor Feature Off")
        db_session.add(org)

    config = await db_session.get(OrgFeatureConfig, org_id)
    if config is None:
        config = OrgFeatureConfig(org_id=org_id, feature_overrides={})
        db_session.add(config)
    config.feature_overrides = {"analytics.competitors": False}
    await db_session.commit()

    try:
        response = client.get("/v1/admin/analytics/competitors", headers=ADMIN_HEADERS)
        assert response.status_code == 403
    finally:
        config.feature_overrides = {}
        await db_session.commit()
