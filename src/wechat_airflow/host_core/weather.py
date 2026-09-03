from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from .settings import HostCoreSettings

_CACHE_LOCK = threading.Lock()
_CACHE: tuple[float, WeatherDecision] | None = None
CACHE_SECONDS = 3_600


@dataclass(frozen=True)
class WeatherDecision:
    send_email: bool
    forecast_date: str | None
    precipitation_mm: float | None
    threshold_mm: float
    reason: str
    error: str | None = None


def evaluate_weather(settings: HostCoreSettings, now: datetime | None = None) -> WeatherDecision:
    global _CACHE

    if not settings.weather_gate_enabled:
        return WeatherDecision(True, None, None, settings.weather_threshold_mm, "disabled")
    current_epoch = time.time()
    with _CACHE_LOCK:
        if _CACHE and current_epoch - _CACHE[0] < CACHE_SECONDS:
            return _CACHE[1]

    shanghai = ZoneInfo("Asia/Shanghai")
    current = (now or datetime.now(shanghai)).astimezone(shanghai)
    target_date = (current.date() + timedelta(days=1)).isoformat()
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": settings.weather_latitude,
                "longitude": settings.weather_longitude,
                "daily": "precipitation_sum",
                "timezone": "Asia/Shanghai",
                "forecast_days": 3,
            },
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        daily = payload.get("daily") if isinstance(payload, dict) else None
        dates = daily.get("time") if isinstance(daily, dict) else None
        values = daily.get("precipitation_sum") if isinstance(daily, dict) else None
        precipitation: float | None = None
        if isinstance(dates, list) and isinstance(values, list):
            for index, value in enumerate(dates):
                if value == target_date and index < len(values):
                    precipitation = float(values[index])
                    break
        if precipitation is None:
            raise RuntimeError("target forecast day is unavailable")
        decision = WeatherDecision(
            precipitation < settings.weather_threshold_mm,
            target_date,
            precipitation,
            settings.weather_threshold_mm,
            "forecast",
        )
    except Exception as exc:
        decision = WeatherDecision(
            True,
            target_date,
            None,
            settings.weather_threshold_mm,
            "weather_unavailable",
            str(exc)[:300],
        )

    with _CACHE_LOCK:
        _CACHE = (current_epoch, decision)
    return decision


def reset_weather_cache_for_test() -> None:
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None
