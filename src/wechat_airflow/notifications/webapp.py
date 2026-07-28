#!/usr/bin/env python3

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

import requests

WEBAPP_OBSERVATION_API_URL_VAR = "WEBAPP_OBSERVATION_API_URL"
WEBAPP_OBSERVATION_API_TOKEN_VAR = "WEBAPP_OBSERVATION_API_TOKEN"
WEBAPP_OBSERVATION_TIMEOUT_SECONDS_VAR = "WEBAPP_OBSERVATION_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 5.0


def _get_variable(key: str, default: Any = None) -> Any:
    from airflow.sdk import Variable

    return Variable.get(key, default=default)


def flatten_court_slots(
    booking_date: str,
    court_data: Mapping[str, Iterable[Iterable[object]]],
) -> list[dict[str, str]]:
    """Convert a venue adapter's court mapping into the web subscription contract."""
    slots: list[dict[str, str]] = []
    for court_name, free_slots in (court_data or {}).items():
        normalized_court_name = str(court_name).strip()
        if not normalized_court_name:
            continue
        for slot in free_slots or []:
            values = list(slot)
            if len(values) < 2:
                continue
            start_time = str(values[0]).strip()
            end_time = str(values[1]).strip()
            if end_time == "24:00":
                end_time = "23:59"
            if len(start_time) != 5 or len(end_time) != 5:
                continue
            slots.append(
                {
                    "date": booking_date,
                    "court_name": normalized_court_name,
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )
    return slots


def publish_venue_observation(
    venue_id: str,
    venue_name: str,
    slots: Iterable[Mapping[str, object]],
    *,
    healthy: bool,
    error: str | None = None,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Publish venue state after legacy delivery without failing the calling DAG."""
    api_url = str(_get_variable(WEBAPP_OBSERVATION_API_URL_VAR, default="")).strip()
    api_token = str(_get_variable(WEBAPP_OBSERVATION_API_TOKEN_VAR, default="")).strip()
    if not api_url or not api_token:
        print("[WEBAPP] observation publishing skipped: configuration is incomplete")
        return {"success": True, "skipped": True, "configured": False}

    try:
        timeout = float(
            _get_variable(
                WEBAPP_OBSERVATION_TIMEOUT_SECONDS_VAR,
                default=str(DEFAULT_TIMEOUT_SECONDS),
            )
        )
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    timeout = min(max(timeout, 0.5), 15.0)

    normalized_slots = []
    for slot in slots:
        normalized_slots.append(
            {
                "date": str(slot.get("date") or "").strip(),
                "court_name": str(slot.get("court_name") or "").strip(),
                "start_time": str(slot.get("start_time") or "").strip(),
                "end_time": str(slot.get("end_time") or "").strip(),
            }
        )

    payload = {
        "venue_id": venue_id,
        "venue_name": venue_name,
        "healthy": bool(healthy),
        "checked_at": (checked_at or datetime.now(UTC)).isoformat(),
        "error": str(error or "")[:300] or None,
        "slots": normalized_slots[:200],
    }
    slot_count = len(normalized_slots[:200])
    try:
        response = requests.post(
            api_url,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        print(
            f"[WEBAPP] observation published venue={venue_id}, "
            f"healthy={healthy}, slots={slot_count}"
        )
        return {"success": True, "slot_count": slot_count}
    except Exception as exc:
        print(f"[WEBAPP] observation publishing failed venue={venue_id}, error={str(exc)[:300]}")
        return {
            "success": False,
            "error": str(exc)[:300],
            "slot_count": slot_count,
        }
