"""Airflow-side client for the Bao'an Tennis Center YDMap scrape."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from wechat_airflow.clients.pi_device import exec_pi_command
from wechat_airflow.venues.dsh_ydmap_client import PiDeviceConfig

VENUE_ID = "baoti"
VENUE_NAME = "宝安网球中心"
DEFAULT_DAYS = 2
BOOKING_URL = "https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317"
SCRAPE_TIMEOUT_SECONDS = 240


def fetch_inspect_payload(config: PiDeviceConfig, *, days: int = DEFAULT_DAYS) -> dict[str, Any]:
    """Call the Raspberry Pi scraper for Bao'an and return its raw JSON payload."""

    url = f"{config.scrape_url}?venue={VENUE_ID}&days={int(days)}"
    command = f"curl -sS --fail --max-time {SCRAPE_TIMEOUT_SECONDS} {quote(url, safe=':/?=&')}"
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
