from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WeatherTrafficRiskLevel = Literal["low", "medium", "high"]


class WeatherTrafficNow(BaseModel):
    temp: float | None = None
    wind_kph: float | None = None
    precip_mm: float | None = None
    snow_cm: float | None = None


class WeatherTrafficHour(BaseModel):
    starts_at: str
    precip_mm: float | None = None
    snow_cm: float | None = None


class WeatherTrafficResponse(BaseModel):
    weather_now: WeatherTrafficNow
    next_6h: list[WeatherTrafficHour] = Field(default_factory=list)
    traffic_hint: str | None = None
    risk_level: WeatherTrafficRiskLevel
    warning: bool = False
