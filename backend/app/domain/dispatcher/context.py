from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from app.domain.dispatcher import route_estimates, schemas

logger = logging.getLogger(__name__)

EDMONTON_LAT = 53.5461
EDMONTON_LNG = -113.4938
CACHE_TTL_SECONDS = 900

_WEATHER_CODE_SUMMARIES: dict[int, str] = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Light freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light rain showers",
    81: "Rain showers",
    82: "Heavy rain showers",
    85: "Light snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm hail",
    99: "Thunderstorm hail",
}

_TRAFFIC_CORRIDORS = (
    ("downtown_west", (53.5461, -113.4938), (53.5146, -113.6073)),
    ("downtown_south", (53.5461, -113.4938), (53.4795, -113.5063)),
)


@dataclass
class _WeatherCacheEntry:
    payload: schemas.DispatcherWeatherPayload
    expires_at: datetime


_WEATHER_CACHE: dict[str, _WeatherCacheEntry] = {}


def _summary_for_code(code: int | None) -> str | None:
    if code is None:
        return None
    return _WEATHER_CODE_SUMMARIES.get(code)


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


def _build_weather_payload(payload: dict[str, object], tz: str) -> schemas.DispatcherWeatherPayload:
    current = payload.get("current") if isinstance(payload, dict) else None
    hourly = payload.get("hourly") if isinstance(payload, dict) else None

    current_temp = None
    current_wind = None
    current_precip = None
    current_snow = None
    current_code = None
    current_time = None

    if isinstance(current, dict):
        current_temp = current.get("temperature_2m")
        current_wind = current.get("wind_speed_10m")
        current_precip = current.get("precipitation")
        current_snow = current.get("snowfall")
        current_code = current.get("weather_code")
        current_time = current.get("time")

    next_hours: list[schemas.DispatcherWeatherHour] = []
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
            next_hours.append(
                schemas.DispatcherWeatherHour(
                    starts_at=time_value,
                    precip_mm=_get_series_value(precip, idx),
                    snow_cm=_get_series_value(snow, idx),
                )
            )

    current_precip_value = float(current_precip) if current_precip is not None else None
    current_snow_value = float(current_snow) if current_snow is not None else None
    current_temp_value = float(current_temp) if current_temp is not None else None
    summary = _summary_for_code(int(current_code)) if current_code is not None else None

    snow_risk = any((hour.snow_cm or 0) > 0.2 for hour in next_hours) or (current_snow_value or 0) > 0.2
    freezing_risk = (
        current_temp_value is not None
        and current_temp_value <= 1.0
        and ((current_precip_value or 0) > 0.2 or (current_snow_value or 0) > 0)
    )

    return schemas.DispatcherWeatherPayload(
        weather_now=schemas.DispatcherWeatherNow(
            temp_c=current_temp_value,
            wind_kph=float(current_wind) if current_wind is not None else None,
            precip_mm=current_precip_value,
            snow_cm=current_snow_value,
            summary=summary,
        ),
        next_6h=next_hours,
        flags=schemas.DispatcherWeatherFlags(
            snow_risk=snow_risk,
            freezing_risk=freezing_risk,
        ),
    )


def _get_cached_weather(tz: str) -> schemas.DispatcherWeatherPayload | None:
    entry = _WEATHER_CACHE.get(tz)
    if not entry:
        return None
    if entry.expires_at <= datetime.now(timezone.utc):
        _WEATHER_CACHE.pop(tz, None)
        return None
    return entry.payload


def _set_cached_weather(tz: str, payload: schemas.DispatcherWeatherPayload) -> None:
    _WEATHER_CACHE[tz] = _WeatherCacheEntry(
        payload=payload,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=CACHE_TTL_SECONDS),
    )


async def fetch_weather(tz: str) -> schemas.DispatcherWeatherPayload:
    cached = _get_cached_weather(tz)
    if cached:
        return cached

    params = {
        "latitude": EDMONTON_LAT,
        "longitude": EDMONTON_LNG,
        "current": "temperature_2m,precipitation,snowfall,weather_code,wind_speed_10m",
        "hourly": "precipitation,snowfall",
        "forecast_days": 2,
        "timezone": tz,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            payload = response.json()
        weather_payload = _build_weather_payload(payload, tz)
    except httpx.HTTPError as exc:
        logger.warning(
            "dispatcher_context_weather_failed",
            extra={"extra": {"error": str(exc), "tz": tz}},
        )
        weather_payload = schemas.DispatcherWeatherPayload(
            weather_now=schemas.DispatcherWeatherNow(),
            next_6h=[],
            flags=schemas.DispatcherWeatherFlags(snow_risk=False, freezing_risk=False),
        )

    _set_cached_weather(tz, weather_payload)
    return weather_payload


def _traffic_bucket(delta_min: int, ratio: float) -> schemas.TrafficRiskLevel:
    if delta_min >= 15 or ratio >= 1.35:
        return "high"
    if delta_min >= 7 or ratio >= 1.2:
        return "medium"
    return "low"


async def fetch_traffic_risk() -> schemas.TrafficRiskLevel:
    now = datetime.now(timezone.utc)
    highest: schemas.TrafficRiskLevel = "low"
    saw_traffic = False
    for _name, origin, dest in _TRAFFIC_CORRIDORS:
        estimate, _ = await route_estimates.estimate_route(
            origin_lat=origin[0],
            origin_lng=origin[1],
            dest_lat=dest[0],
            dest_lng=dest[1],
            depart_at=now,
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
            return bucket
        if bucket == "medium" and highest == "low":
            highest = bucket
    if not saw_traffic:
        return "low"
    return highest


async def fetch_dispatcher_context(tz: str) -> schemas.DispatcherContextResponse:
    weather_payload = await fetch_weather(tz)
    traffic_risk = await fetch_traffic_risk()
    return schemas.DispatcherContextResponse(
        weather_now=weather_payload.weather_now,
        next_6h=weather_payload.next_6h,
        flags=weather_payload.flags,
        traffic_risk=traffic_risk,
    )
