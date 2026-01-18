from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from math import asin, ceil, cos, radians, sin, sqrt
from typing import Literal
import uuid

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.integrations.db_models import MapsUsage
from app.infra.security import InMemoryRateLimiter
from app.settings import settings

CACHE_TTL_SECONDS = 600
CACHE_BUCKET_SECONDS = 300
CACHE_COORD_DECIMALS = 3
AVERAGE_SPEED_KMH = 35
MIN_DURATION_MIN = 5

MAPS_HTTP_TRANSPORT: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True)
class MapsMatrixElement:
    distance_km: float
    duration_min: int
    duration_in_traffic_min: int | None
    provider: Literal["google", "heuristic"]

    def as_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MapsMatrixResult:
    matrix: list[list[MapsMatrixElement]]
    provider: Literal["google", "heuristic"]
    warning: str | None

    def as_payload(self) -> dict[str, object]:
        return {
            "matrix": [[element.as_payload() for element in row] for row in self.matrix],
            "provider": self.provider,
            "warning": self.warning,
        }


@dataclass
class _CacheEntry:
    value: MapsMatrixResult
    expires_at: datetime


_CACHE: dict[str, _CacheEntry] = {}
_RATE_LIMITER = InMemoryRateLimiter(
    requests_per_minute=settings.maps_requests_per_minute,
    cleanup_minutes=settings.rate_limit_cleanup_minutes,
)


def clear_cache() -> None:
    _CACHE.clear()


def _round_coord(value: float) -> float:
    return round(value, CACHE_COORD_DECIMALS)


def _normalize_depart_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _cache_key(
    origins: list[tuple[float, float]],
    destinations: list[tuple[float, float]],
    depart_at: datetime | None,
    mode: str,
) -> str:
    bucket_time = (_normalize_depart_at(depart_at) or datetime.now(timezone.utc)).timestamp()
    bucket = int(bucket_time // CACHE_BUCKET_SECONDS)
    origin_key = "|".join(f"{_round_coord(lat)},{_round_coord(lng)}" for lat, lng in origins)
    dest_key = "|".join(f"{_round_coord(lat)},{_round_coord(lng)}" for lat, lng in destinations)
    return f"{origin_key}->{dest_key}|{mode}|{bucket}"


def _get_cached(key: str) -> MapsMatrixResult | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    if entry.expires_at <= datetime.now(timezone.utc):
        _CACHE.pop(key, None)
        return None
    return entry.value


def _set_cached(key: str, value: MapsMatrixResult) -> None:
    _CACHE[key] = _CacheEntry(
        value=value,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=CACHE_TTL_SECONDS),
    )


def _haversine_km(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> float:
    radius_km = 6371.0
    lat1 = radians(origin_lat)
    lat2 = radians(dest_lat)
    delta_lat = radians(dest_lat - origin_lat)
    delta_lng = radians(dest_lng - origin_lng)
    a = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lng / 2) ** 2
    c = 2 * asin(sqrt(a))
    return radius_km * c


def _heuristic_element(origin: tuple[float, float], dest: tuple[float, float]) -> MapsMatrixElement:
    distance_km = _haversine_km(origin[0], origin[1], dest[0], dest[1])
    duration_hours = distance_km / AVERAGE_SPEED_KMH if AVERAGE_SPEED_KMH else 0
    duration_min = max(int(ceil(duration_hours * 60)), MIN_DURATION_MIN)
    return MapsMatrixElement(
        distance_km=round(distance_km, 2),
        duration_min=duration_min,
        duration_in_traffic_min=None,
        provider="heuristic",
    )


async def allow_maps_request(org_id: uuid.UUID) -> bool:
    return await _RATE_LIMITER.allow(f"maps:{org_id}")


def _build_matrix(origins: list[tuple[float, float]], destinations: list[tuple[float, float]]) -> list[list[MapsMatrixElement]]:
    return [[_heuristic_element(origin, dest) for dest in destinations] for origin in origins]


def _month_bounds(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1)
    else:
        end = start.replace(month=start.month + 1, day=1)
    return start, end


async def record_usage(session: AsyncSession, org_id: uuid.UUID, day: date, count: int) -> None:
    if count <= 0:
        return
    record = await session.get(MapsUsage, {"org_id": org_id, "day": day})
    if record:
        record.count += count
    else:
        session.add(MapsUsage(org_id=org_id, day=day, count=count))
    await session.flush()


async def get_month_usage(session: AsyncSession, org_id: uuid.UUID, today: date | None = None) -> int:
    now = today or datetime.now(timezone.utc).date()
    start, end = _month_bounds(now)
    result = await session.execute(
        sa.select(sa.func.coalesce(sa.func.sum(MapsUsage.count), 0)).where(
            MapsUsage.org_id == org_id,
            MapsUsage.day >= start,
            MapsUsage.day < end,
        )
    )
    return int(result.scalar() or 0)


def get_month_label(today: date | None = None) -> str:
    now = today or datetime.now(timezone.utc).date()
    return now.strftime("%Y-%m")


def get_month_limit() -> int:
    return max(settings.maps_monthly_quota_limit, 0)


def _distance_matrix_params(
    origins: list[tuple[float, float]],
    destinations: list[tuple[float, float]],
    depart_at: datetime | None,
    mode: str,
) -> dict[str, object]:
    depart_value: str | int
    if depart_at:
        depart_value = int(_normalize_depart_at(depart_at).timestamp())
    else:
        depart_value = "now"
    return {
        "origins": "|".join(f"{lat},{lng}" for lat, lng in origins),
        "destinations": "|".join(f"{lat},{lng}" for lat, lng in destinations),
        "mode": mode,
        "units": "metric",
        "departure_time": depart_value,
        "key": settings.google_maps_api_key,
    }


def _build_google_matrix(
    origins: list[tuple[float, float]],
    destinations: list[tuple[float, float]],
    payload: dict[str, object],
) -> tuple[list[list[MapsMatrixElement]], bool]:
    rows = payload.get("rows") or []
    matrix: list[list[MapsMatrixElement]] = []
    had_fallback = False
    for origin_index, origin in enumerate(origins):
        row_payload = rows[origin_index] if origin_index < len(rows) else None
        elements_payload = row_payload.get("elements") if isinstance(row_payload, dict) else None
        row: list[MapsMatrixElement] = []
        for dest_index, dest in enumerate(destinations):
            element_payload = (
                elements_payload[dest_index]
                if isinstance(elements_payload, list) and dest_index < len(elements_payload)
                else None
            )
            if not element_payload or element_payload.get("status") != "OK":
                row.append(_heuristic_element(origin, dest))
                had_fallback = True
                continue
            distance = element_payload.get("distance", {}).get("value")
            duration = element_payload.get("duration", {}).get("value")
            if distance is None or duration is None:
                row.append(_heuristic_element(origin, dest))
                had_fallback = True
                continue
            duration_in_traffic = element_payload.get("duration_in_traffic", {}).get("value")
            distance_km = float(distance) / 1000
            duration_min = int(ceil(float(duration) / 60))
            duration_in_traffic_min = (
                int(ceil(float(duration_in_traffic) / 60)) if duration_in_traffic is not None else None
            )
            row.append(
                MapsMatrixElement(
                    distance_km=round(distance_km, 2),
                    duration_min=duration_min,
                    duration_in_traffic_min=duration_in_traffic_min,
                    provider="google",
                )
            )
        matrix.append(row)
    return matrix, had_fallback


async def fetch_distance_matrix(
    *,
    session: AsyncSession,
    org_id: uuid.UUID,
    origins: list[tuple[float, float]],
    destinations: list[tuple[float, float]],
    depart_at: datetime | None,
    mode: str,
) -> tuple[MapsMatrixResult, bool, bool]:
    cache_key = _cache_key(origins, destinations, depart_at, mode)
    cached = _get_cached(cache_key)
    if cached:
        return cached, True, False

    key_configured = bool(settings.google_maps_api_key)
    if not key_configured:
        result = MapsMatrixResult(
            matrix=_build_matrix(origins, destinations),
            provider="heuristic",
            warning="missing_key",
        )
        _set_cached(cache_key, result)
        return result, False, False

    total_elements = len(origins) * len(destinations)
    month_used = await get_month_usage(session, org_id)
    limit = get_month_limit()
    if limit and month_used + total_elements > limit:
        result = MapsMatrixResult(
            matrix=_build_matrix(origins, destinations),
            provider="heuristic",
            warning="quota_exceeded",
        )
        _set_cached(cache_key, result)
        return result, False, False

    params = _distance_matrix_params(origins, destinations, depart_at, mode)
    try:
        async with httpx.AsyncClient(timeout=5.0, transport=MAPS_HTTP_TRANSPORT) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError:
        result = MapsMatrixResult(
            matrix=_build_matrix(origins, destinations),
            provider="heuristic",
            warning="provider_error",
        )
        _set_cached(cache_key, result)
        return result, False, False

    if payload.get("status") != "OK":
        result = MapsMatrixResult(
            matrix=_build_matrix(origins, destinations),
            provider="heuristic",
            warning="provider_error",
        )
        _set_cached(cache_key, result)
        return result, False, False

    matrix, had_fallback = _build_google_matrix(origins, destinations, payload)
    warning = "partial_fallback" if had_fallback else None
    result = MapsMatrixResult(matrix=matrix, provider="google", warning=warning)
    _set_cached(cache_key, result)
    await record_usage(session, org_id, datetime.now(timezone.utc).date(), total_elements)
    return result, False, True


async def test_api_key() -> tuple[bool, str]:
    if not settings.google_maps_api_key:
        return False, "missing_key"
    params = _distance_matrix_params(
        origins=[(0.0, 0.0)],
        destinations=[(0.0, 0.0)],
        depart_at=None,
        mode="driving",
    )
    try:
        async with httpx.AsyncClient(timeout=5.0, transport=MAPS_HTTP_TRANSPORT) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError:
        return False, "provider_error"
    status = payload.get("status")
    if status != "OK":
        return False, str(status or "provider_error")
    return True, "ok"
