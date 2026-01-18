from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from app.domain.dashboard import schemas
from app.domain.dispatcher import route_estimates
from app.settings import settings

logger = logging.getLogger(__name__)

EDMONTON_LAT = 53.5461
EDMONTON_LNG = -113.4938
CACHE_TTL_SECONDS = 900
CACHE_BUCKET_SECONDS = 300

_TRAFFIC_CORRIDORS = (
    ("downtown_west", (53.5461, -113.4938), (53.5146, -113.6073)),
    ("downtown_south", (53.5461, -113.4938), (53.4795, -113.5063)),
)

_TRAFFIC_HINTS: dict[schemas.WeatherTrafficRiskLevel, str] = {
    "low": "Traffic is flowing normally.",
    "medium": "Moderate congestion — allow extra travel time.",
    "high": "Heavy congestion — delays likely.",
}


@dataclass
class _WeatherCacheEntry:
    payload: tuple[schemas.WeatherTrafficNow, list[schemas.WeatherTrafficHour]]
    expires_at: datetime


@dataclass
class _TrafficCacheEntry:
    risk_level: schemas.WeatherTrafficRiskLevel
    traffic_hint: str | None
    expires_at: datetime


_WEATHER_CACHE: dict[str, _WeatherCacheEntry] = {}
_TRAFFIC_CACHE: dict[str, _TrafficCacheEntry] = {}


def _normalize_as_of(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _cache_bucket_key(as_of: datetime) -> str:
    bucket = int(as_of.timestamp() // CACHE_BUCKET_SECONDS)
    return str(bucket)


def _get_cached_weather(key: str) -> tuple[schemas.WeatherTrafficNow, list[schemas.WeatherTrafficHour]] | None:
    entry = _WEATHER_CACHE.get(key)
    if not entry:
        return None
    if entry.expires_at <= datetime.now(timezone.utc):
        _WEATHER_CACHE.pop(key, None)
        return None
    return entry.payload


def _set_cached_weather(
    key: str,
    payload: tuple[schemas.WeatherTrafficNow, list[schemas.WeatherTrafficHour]],
) -> None:
    _WEATHER_CACHE[key] = _WeatherCacheEntry(
        payload=payload,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=CACHE_TTL_SECONDS),
    )


def _get_cached_traffic(key: str) -> _TrafficCacheEntry | None:
    entry = _TRAFFIC_CACHE.get(key)
    if not entry:
        return None
    if entry.expires_at <= datetime.now(timezone.utc):
        _TRAFFIC_CACHE.pop(key, None)
        return None
    return entry


def _set_cached_traffic(key: str, entry: _TrafficCacheEntry) -> None:
    _TRAFFIC_CACHE[key] = entry


def _get_series_value(series: list[object] | None, index: int) -> float | None:
    if not series or index < 0 or index >= len(series):
        return None
    value = series[index]
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_starts_at(value: str, tz: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    try:
        zone = ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        zone = timezone.utc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    else:
        parsed = parsed.astimezone(zone)
    return parsed.isoformat()


def _build_weather_payload(
    payload: dict[str, object], tz: str
) -> tuple[schemas.WeatherTrafficNow, list[schemas.WeatherTrafficHour]]:
    current = payload.get("current") if isinstance(payload, dict) else None
    hourly = payload.get("hourly") if isinstance(payload, dict) else None

    current_temp = None
    current_wind = None
    current_precip = None
    current_snow = None
    current_time = None

    if isinstance(current, dict):
        current_temp = current.get("temperature_2m")
        current_wind = current.get("wind_speed_10m")
        current_precip = current.get("precipitation")
        current_snow = current.get("snowfall")
        current_time = current.get("time")

    next_hours: list[schemas.WeatherTrafficHour] = []
    if isinstance(hourly, dict):
        times = hourly.get("time") or []
        precip = hourly.get("precipitation") or []
        snow = hourly.get("snowfall") or []
        start_index = 0
        if current_time in times:
            start_index = times.index(current_time)
        elif times:
            try:
                now_local = datetime.now(ZoneInfo(tz)).replace(minute=0, second=0, microsecond=0)
                now_local_str = now_local.isoformat(timespec="minutes")
                if now_local_str in times:
                    start_index = times.index(now_local_str)
            except Exception:  # noqa: BLE001
                start_index = 0
        for idx in range(start_index, min(start_index + 6, len(times))):
            time_value = times[idx]
            if not isinstance(time_value, str):
                continue
            formatted_time = _format_starts_at(time_value, tz)
            if not formatted_time:
                continue
            next_hours.append(
                schemas.WeatherTrafficHour(
                    starts_at=formatted_time,
                    precip_mm=_get_series_value(precip, idx),
                    snow_cm=_get_series_value(snow, idx),
                )
            )

    return (
        schemas.WeatherTrafficNow(
            temp=float(current_temp) if current_temp is not None else None,
            wind_kph=float(current_wind) if current_wind is not None else None,
            precip_mm=float(current_precip) if current_precip is not None else None,
            snow_cm=float(current_snow) if current_snow is not None else None,
        ),
        next_hours,
    )


async def _fetch_weather(*, tz: str, as_of: datetime) -> tuple[
    schemas.WeatherTrafficNow,
    list[schemas.WeatherTrafficHour],
    bool,
]:
    cache_key = f"{tz}:{_cache_bucket_key(as_of)}"
    cached = _get_cached_weather(cache_key)
    if cached:
        weather_now, next_6h = cached
        return weather_now, next_6h, False

    params = {
        "latitude": EDMONTON_LAT,
        "longitude": EDMONTON_LNG,
        "current": "temperature_2m,precipitation,snowfall,wind_speed_10m",
        "hourly": "precipitation,snowfall",
        "forecast_days": 2,
        "timezone": tz,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            payload = response.json()
        weather_now, next_6h = _build_weather_payload(payload, tz)
    except httpx.HTTPError as exc:
        logger.warning(
            "dashboard_weather_traffic_weather_failed",
            extra={"extra": {"error": str(exc), "tz": tz}},
        )
        weather_now = schemas.WeatherTrafficNow()
        next_6h = []
        return weather_now, next_6h, True

    _set_cached_weather(cache_key, (weather_now, next_6h))
    return weather_now, next_6h, False


def _traffic_bucket(delta_min: int, ratio: float) -> schemas.WeatherTrafficRiskLevel:
    if delta_min >= 15 or ratio >= 1.35:
        return "high"
    if delta_min >= 7 or ratio >= 1.2:
        return "medium"
    return "low"


async def _fetch_traffic(*, as_of: datetime) -> tuple[
    schemas.WeatherTrafficRiskLevel,
    str | None,
    bool,
]:
    cache_key = _cache_bucket_key(as_of)
    cached = _get_cached_traffic(cache_key)
    if cached:
        return cached.risk_level, cached.traffic_hint, False

    highest: schemas.WeatherTrafficRiskLevel = "low"
    saw_traffic = False
    for _name, origin, dest in _TRAFFIC_CORRIDORS:
        estimate, _ = await route_estimates.estimate_route(
            origin_lat=origin[0],
            origin_lng=origin[1],
            dest_lat=dest[0],
            dest_lng=dest[1],
            depart_at=as_of,
            mode="traffic",
        )
        if estimate.duration_in_traffic_min is None:
            continue
        saw_traffic = True
        baseline = max(estimate.duration_min, 1)
        delta = max(estimate.duration_in_traffic_min - estimate.duration_min, 0)
        ratio = estimate.duration_in_traffic_min / baseline
        bucket = _traffic_bucket(delta, ratio)
        if bucket == "high":
            highest = bucket
            break
        if bucket == "medium" and highest == "low":
            highest = bucket

    if not saw_traffic:
        hint = None
        risk = "low"
        warning = True
    else:
        risk = highest
        hint = _TRAFFIC_HINTS.get(risk)
        warning = False

    entry = _TrafficCacheEntry(
        risk_level=risk,
        traffic_hint=hint,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=CACHE_TTL_SECONDS),
    )
    _set_cached_traffic(cache_key, entry)
    return risk, hint, warning


async def fetch_weather_traffic(
    *,
    org_timezone: str,
    as_of: datetime | None,
) -> schemas.WeatherTrafficResponse:
    if settings.weather_traffic_mode == "off":
        return schemas.WeatherTrafficResponse(
            weather_now=schemas.WeatherTrafficNow(),
            next_6h=[],
            traffic_hint=None,
            risk_level="low",
            warning=True,
        )

    normalized_as_of = _normalize_as_of(as_of)
    weather_now, next_6h, weather_warning = await _fetch_weather(
        tz=org_timezone, as_of=normalized_as_of
    )
    risk_level, traffic_hint, traffic_warning = await _fetch_traffic(as_of=normalized_as_of)

    warning = weather_warning or traffic_warning

    return schemas.WeatherTrafficResponse(
        weather_now=weather_now,
        next_6h=next_6h,
        traffic_hint=traffic_hint,
        risk_level=risk_level,
        warning=warning,
    )
