from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import asin, ceil, cos, radians, sin, sqrt
from typing import Literal

import httpx

from app.settings import settings

CACHE_TTL_SECONDS = 600
CACHE_BUCKET_SECONDS = 300
CACHE_COORD_DECIMALS = 3
AVERAGE_SPEED_KMH = 35
MIN_DURATION_MIN = 5


@dataclass(frozen=True)
class RouteEstimate:
    distance_km: float
    duration_min: int
    duration_in_traffic_min: int | None
    provider: Literal["google", "heuristic"]

    def as_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class _CacheEntry:
    value: RouteEstimate
    expires_at: datetime


_CACHE: dict[str, _CacheEntry] = {}


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
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    depart_at: datetime | None,
    mode: str,
) -> str:
    bucket_time = (_normalize_depart_at(depart_at) or datetime.now(timezone.utc)).timestamp()
    bucket = int(bucket_time // CACHE_BUCKET_SECONDS)
    return (
        f"{_round_coord(origin_lat)},{_round_coord(origin_lng)}->"
        f"{_round_coord(dest_lat)},{_round_coord(dest_lng)}|{mode}|{bucket}"
    )


def _get_cached(key: str) -> RouteEstimate | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    if entry.expires_at <= datetime.now(timezone.utc):
        _CACHE.pop(key, None)
        return None
    return entry.value


def _set_cached(key: str, estimate: RouteEstimate) -> None:
    _CACHE[key] = _CacheEntry(
        value=estimate,
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


def estimate_route_heuristic(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
) -> RouteEstimate:
    distance_km = _haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
    duration_hours = distance_km / AVERAGE_SPEED_KMH if AVERAGE_SPEED_KMH else 0
    duration_min = max(int(ceil(duration_hours * 60)), MIN_DURATION_MIN)
    return RouteEstimate(
        distance_km=round(distance_km, 2),
        duration_min=duration_min,
        duration_in_traffic_min=None,
        provider="heuristic",
    )


async def _estimate_google(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    depart_at: datetime | None,
) -> RouteEstimate | None:
    api_key = settings.google_maps_api_key
    if not api_key:
        return None
    params: dict[str, object] = {
        "origins": f"{origin_lat},{origin_lng}",
        "destinations": f"{dest_lat},{dest_lng}",
        "mode": "driving",
        "units": "metric",
        "key": api_key,
        "departure_time": int(_normalize_depart_at(depart_at).timestamp()) if depart_at else "now",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json", params=params
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError:
        return None
    if payload.get("status") != "OK":
        return None
    rows = payload.get("rows") or []
    if not rows:
        return None
    elements = rows[0].get("elements") if isinstance(rows[0], dict) else None
    if not elements:
        return None
    element = elements[0]
    if element.get("status") != "OK":
        return None
    distance = element.get("distance", {}).get("value")
    duration = element.get("duration", {}).get("value")
    if distance is None or duration is None:
        return None
    duration_in_traffic = element.get("duration_in_traffic", {}).get("value")
    distance_km = float(distance) / 1000
    duration_min = int(ceil(float(duration) / 60))
    duration_in_traffic_min = (
        int(ceil(float(duration_in_traffic) / 60)) if duration_in_traffic is not None else None
    )
    return RouteEstimate(
        distance_km=round(distance_km, 2),
        duration_min=duration_min,
        duration_in_traffic_min=duration_in_traffic_min,
        provider="google",
    )


async def estimate_route(
    *,
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    depart_at: datetime | None,
    mode: str,
) -> tuple[RouteEstimate, bool]:
    key = _cache_key(origin_lat, origin_lng, dest_lat, dest_lng, depart_at, mode)
    cached = _get_cached(key)
    if cached:
        return cached, True

    estimate = await _estimate_google(origin_lat, origin_lng, dest_lat, dest_lng, depart_at)
    if estimate is None:
        estimate = estimate_route_heuristic(origin_lat, origin_lng, dest_lat, dest_lng)

    _set_cached(key, estimate)
    return estimate, False
