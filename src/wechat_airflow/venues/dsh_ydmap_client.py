from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from wechat_airflow.clients.pi_device import exec_pi_command

CONFIG_VARIABLE = "PI_DEVICE_SSH"
DEFAULT_SCRAPE_URL = "http://127.0.0.1:8788/inspect"
DEFAULT_DAYS = 5
TIME_WIDTH = 5

CourtAvailability = dict[str, list[list[str]]]


@dataclass(frozen=True)
class PiDeviceConfig:
    host: str
    port: int
    username: str
    password: str
    host_key_sha256: str
    scrape_url: str = DEFAULT_SCRAPE_URL

    @classmethod
    def from_value(cls, value: object) -> PiDeviceConfig:
        if not isinstance(value, dict):
            raise ValueError("PI_DEVICE_SSH must be a JSON object")
        host = str(value.get("host") or "").strip()
        username = str(value.get("username") or "").strip()
        password = str(value.get("password") or "")
        host_key = str(value.get("host_key_sha256") or "").strip()
        scrape_url = str(value.get("scrape_url") or DEFAULT_SCRAPE_URL).strip()
        raw_port = value.get("port")
        if raw_port is None:
            raise ValueError("PI_DEVICE_SSH.port must be an integer")
        try:
            port = int(raw_port)
        except (TypeError, ValueError) as exc:
            raise ValueError("PI_DEVICE_SSH.port must be an integer") from exc
        if not host or not username or not password or not host_key or port <= 0:
            raise ValueError("PI_DEVICE_SSH is missing required SSH fields")
        if not scrape_url.startswith("http://") and not scrape_url.startswith("https://"):
            raise ValueError("PI_DEVICE_SSH.scrape_url must be an HTTP URL")
        return cls(
            host=host,
            port=port,
            username=username,
            password=password,
            host_key_sha256=host_key,
            scrape_url=scrape_url,
        )


def _normalize_time(value: object) -> str | None:
    text = str(value or "").strip()
    if len(text) != TIME_WIDTH or text[2] != ":":
        return None
    try:
        hours = int(text[:2])
        minutes = int(text[3:])
    except ValueError:
        return None
    if hours == 24 and minutes == 0:
        return "24:00"
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return f"{hours:02d}:{minutes:02d}"


def parse_inspect_payload(payload: object) -> dict[str, CourtAvailability]:
    if not isinstance(payload, dict):
        raise ValueError("scrape payload must be an object")
    if payload.get("captcha") is True:
        raise ValueError("scrape blocked by captcha")
    if payload.get("ok") is not True:
        raise ValueError(str(payload.get("error") or "scrape failed"))
    days = payload.get("days")
    if not isinstance(days, list):
        raise ValueError("scrape payload days must be a list")
    parsed: dict[str, CourtAvailability] = {}
    for raw_day in days:
        if not isinstance(raw_day, dict):
            continue
        booking_date = str(raw_day.get("date") or "").strip()
        courts = raw_day.get("courts")
        if len(booking_date) != 10 or not isinstance(courts, dict):
            continue
        availability: CourtAvailability = {}
        for court_name, ranges in courts.items():
            normalized_name = str(court_name).strip()
            if not normalized_name or not isinstance(ranges, list):
                continue
            slots: list[list[str]] = []
            for raw_slot in ranges:
                if not isinstance(raw_slot, list | tuple) or len(raw_slot) < 2:
                    continue
                start = _normalize_time(raw_slot[0])
                end = _normalize_time(raw_slot[1])
                if start is None or end is None or start >= end:
                    continue
                slots.append([start, end])
            if slots:
                availability[normalized_name] = slots
        parsed[booking_date] = availability
    return parsed


def fetch_inspect_payload(config: PiDeviceConfig, *, days: int = DEFAULT_DAYS) -> dict[str, Any]:
    url = f"{config.scrape_url}?days={int(days)}"
    command = f"curl -sS --fail --max-time 150 {quote(url, safe=':/?=&')}"
    output, error, status = exec_pi_command(
        config.host,
        config.port,
        config.username,
        config.password,
        config.host_key_sha256,
        command,
    )
    if status != 0 or not output:
        raise RuntimeError(error or "pi scrape command failed")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("pi scrape returned non-JSON output") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("pi scrape returned a non-object JSON payload")
    return payload
