from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

import requests

from wechat_airflow.notification_core.config import NotificationCoreSettings


@dataclass(frozen=True)
class WeatherDecision:
    send_email: bool
    precipitation_mm: float | None
    threshold_mm: float
    reason: str


_CACHE_LOCK = threading.Lock()
_CACHE: tuple[float, WeatherDecision] | None = None


def evaluate_weather(settings: NotificationCoreSettings) -> WeatherDecision:
    if not settings.weather_gate_enabled:
        return WeatherDecision(True, None, settings.weather_precipitation_threshold_mm, "disabled")

    global _CACHE
    now = time.time()
    with _CACHE_LOCK:
        if _CACHE and _CACHE[0] > now:
            return _CACHE[1]

    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": settings.weather_latitude,
                "longitude": settings.weather_longitude,
                "daily": "precipitation_sum",
                "forecast_days": 1,
                "timezone": "Asia/Shanghai",
            },
            timeout=(5, 10),
        )
        response.raise_for_status()
        payload: Any = response.json()
        daily = payload.get("daily") if isinstance(payload, Mapping) else None
        values = daily.get("precipitation_sum") if isinstance(daily, Mapping) else None
        precipitation = float(values[0]) if isinstance(values, list) and values else None
        decision = WeatherDecision(
            send_email=(
                precipitation is None
                or precipitation < settings.weather_precipitation_threshold_mm
            ),
            precipitation_mm=precipitation,
            threshold_mm=settings.weather_precipitation_threshold_mm,
            reason="forecast",
        )
    except Exception as exc:
        # Weather is an optional suppression policy. Provider failure must not
        # become another single point of failure for availability alerts.
        decision = WeatherDecision(
            True,
            None,
            settings.weather_precipitation_threshold_mm,
            f"weather_unavailable:{type(exc).__name__}",
        )

    with _CACHE_LOCK:
        _CACHE = (now + 600, decision)
    return decision
