from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from .settings import HostCoreSettings

_CACHE_LOCK = threading.Lock()
_CACHE: dict[tuple[str, float, float, float], tuple[float, WeatherDecision]] = {}
CACHE_SECONDS = 3_600


@dataclass(frozen=True)
class WeatherDecision:
    send_email: bool
    forecast_date: str | None
    precipitation_mm: float | None
    threshold_mm: float
    reason: str
    error: str | None = None


def evaluate_weather(
    settings: HostCoreSettings,
    now: datetime | None = None,
    *,
    booking_date: str | None = None,
) -> WeatherDecision:
    """Evaluate the actual booking date, not a blanket 'tomorrow' gate."""
    if not settings.weather_gate_enabled:
        return WeatherDecision(True, booking_date, None, settings.weather_threshold_mm, "disabled")
    shanghai = ZoneInfo("Asia/Shanghai")
    current = (now or datetime.now(shanghai)).astimezone(shanghai)
    target = date.fromisoformat(booking_date) if booking_date else current.date()
    key = (
        target.isoformat(),
        settings.weather_latitude,
        settings.weather_longitude,
        settings.weather_threshold_mm,
    )
    epoch = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and epoch - cached[0] < (CACHE_SECONDS if cached[1].error is None else 60):
            return cached[1]
    try:
        offset = (target - current.date()).days
        if not 0 <= offset < 16:
            raise ValueError("booking day outside forecast horizon")
        params: dict[str, str | float | int] = {
            "latitude": settings.weather_latitude,
            "longitude": settings.weather_longitude,
            "daily": "precipitation_sum",
            "timezone": "Asia/Shanghai",
            "forecast_days": max(3, offset + 1),
        }
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            timeout=8,
        )
        response.raise_for_status()
        daily = response.json()["daily"]
        index = daily["time"].index(target.isoformat())
        precipitation = float(daily["precipitation_sum"][index])
        if not math.isfinite(precipitation) or precipitation < 0:
            raise ValueError("invalid precipitation")
        allowed = precipitation < settings.weather_threshold_mm
        decision = WeatherDecision(
            allowed,
            target.isoformat(),
            precipitation,
            settings.weather_threshold_mm,
            "forecast" if allowed else "precipitation_threshold_met",
        )
    except Exception as exc:
        # Weather outages cannot silently disable the notification system.
        decision = WeatherDecision(
            True,
            target.isoformat(),
            None,
            settings.weather_threshold_mm,
            "weather_unavailable",
            type(exc).__name__,
        )
    with _CACHE_LOCK:
        if len(_CACHE) >= 64:
            _CACHE.clear()
        _CACHE[key] = (epoch, decision)
    return decision


def reset_weather_cache_for_test() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
