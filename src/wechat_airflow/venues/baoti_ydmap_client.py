"""Airflow-side client for the Bao'an Tennis Center YDMap scrape."""

from __future__ import annotations

import json
import shlex
from datetime import date
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from wechat_airflow.clients.pi_device import exec_pi_command
from wechat_airflow.venues.dsh_ydmap_client import (
    CourtAvailability,
    PiDeviceConfig,
)
from wechat_airflow.venues.dsh_ydmap_client import (
    parse_inspect_payload as parse_ydmap_payload,
)

VENUE_ID = "baoti"
VENUE_NAME = "宝安网球中心"
DEFAULT_DAYS = 2
BOOKING_URL = "https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317"
SCRAPE_TIMEOUT_SECONDS = 240
SSH_TIMEOUT_SECONDS = SCRAPE_TIMEOUT_SECONDS + 30
SCHEMA_VERSION = 2
SOURCE_HOST = "bawtt.ydmap.cn"
SOURCE_SALES_ID = "104036"
FRESHNESS_PROOF = "both_source_arrays_replaced_after_date_selection"
EXPECTED_SALES_ITEM_IDS = frozenset({"111317", "103224", "111319"})
EXPECTED_GROUP_LABELS = {"outdoor": "室外", "indoor": "室内", "windrain": "风雨"}


def parse_inspect_payload(
    payload: object, *, expected_dates: set[str]
) -> dict[str, CourtAvailability]:
    """Accept only complete, date-bound Bao'an observations from the new scraper."""

    if not isinstance(payload, dict):
        raise ValueError("baoti scrape payload must be an object")
    if (
        type(payload.get("schema_version")) is not int
        or payload["schema_version"] != SCHEMA_VERSION
    ):
        raise ValueError("baoti scrape protocol version mismatch")
    if payload.get("venue") != VENUE_ID:
        raise ValueError("baoti scrape venue mismatch")
    availability = parse_ydmap_payload(payload)
    raw_days = payload.get("days")
    if (
        not isinstance(raw_days, list)
        or len(raw_days) != len(expected_dates)
        or set(availability) != expected_dates
    ):
        raise ValueError("baoti scrape date coverage mismatch")
    seen_dates: set[str] = set()
    for raw_day in raw_days:
        if not isinstance(raw_day, dict):
            raise ValueError("baoti scrape day must be an object")
        booking_date = raw_day.get("date")
        if (
            not isinstance(booking_date, str)
            or date.fromisoformat(booking_date).isoformat() != booking_date
        ):
            raise ValueError("baoti scrape date is invalid")
        if booking_date in seen_dates:
            raise ValueError("baoti scrape duplicate date")
        seen_dates.add(booking_date)
        groups = raw_day.get("groups")
        if not isinstance(groups, list) or len(groups) != len(EXPECTED_GROUP_LABELS):
            raise ValueError("baoti scrape group evidence is incomplete")
        seen_groups: set[str] = set()
        seen_products: set[str] = set()
        known_courts: set[str] = set()
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError("baoti scrape group evidence is invalid")
            key = group.get("key")
            sales_item_id = group.get("sales_item_id")
            if (
                not isinstance(key, str)
                or key not in EXPECTED_GROUP_LABELS
                or key in seen_groups
                or not isinstance(sales_item_id, str)
                or sales_item_id not in EXPECTED_SALES_ITEM_IDS
                or sales_item_id in seen_products
            ):
                raise ValueError("baoti scrape product evidence mismatch")
            if (
                group.get("source_date") != booking_date
                or group.get("selected_date") != booking_date
            ):
                raise ValueError("baoti scrape source date mismatch")
            if (
                group.get("source_host") != SOURCE_HOST
                or group.get("source_sales_id") != SOURCE_SALES_ID
                or group.get("freshness") != FRESHNESS_PROOF
            ):
                raise ValueError("baoti scrape source identity or freshness proof mismatch")
            generation = group.get("load_generation")
            versions = group.get("data_version")
            if (
                type(generation) is not int
                or generation < 1
                or not isinstance(versions, dict)
                or any(
                    type(versions.get(name)) is not int or versions[name] < 1
                    for name in ("platforms", "orders")
                )
            ):
                raise ValueError("baoti scrape source generation is invalid")
            product_name = group.get("product_name")
            if not isinstance(product_name, str) or EXPECTED_GROUP_LABELS[key] not in product_name:
                raise ValueError("baoti scrape product name mismatch")
            court_names = group.get("court_names")
            cell_count = group.get("cell_count")
            if (
                not isinstance(court_names, list)
                or not court_names
                or any(not isinstance(name, str) or not name.strip() for name in court_names)
                or type(cell_count) is not int
                or cell_count <= 0
            ):
                raise ValueError("baoti scrape grid evidence is incomplete")
            known_courts.update(court_names)
            seen_groups.add(key)
            seen_products.add(sales_item_id)
        raw_courts = raw_day.get("courts")
        if not isinstance(raw_courts, dict) or not set(raw_courts).issubset(known_courts):
            raise ValueError("baoti scrape court identity mismatch")
        for court_name, ranges in raw_courts.items():
            if (
                not isinstance(ranges, list)
                or any(not isinstance(slot, list) or len(slot) != 2 for slot in ranges)
                or len(ranges) != len(availability[booking_date].get(court_name, []))
            ):
                raise ValueError("baoti scrape slot payload is invalid")
    return availability


def fetch_inspect_payload(config: PiDeviceConfig, *, days: int = DEFAULT_DAYS) -> dict[str, Any]:
    """Call the Raspberry Pi scraper for Bao'an and return its raw JSON payload."""

    parts = urlsplit(config.scrape_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in {"venue", "days"}
    ]
    query.extend((("venue", VENUE_ID), ("days", str(int(days)))))
    url = urlunsplit(parts._replace(query=urlencode(query)))
    command = f"curl -sS --fail --max-time {SCRAPE_TIMEOUT_SECONDS} {shlex.quote(url)}"
    output, error, status = exec_pi_command(
        config.host,
        config.port,
        config.username,
        config.password,
        config.host_key_sha256,
        command,
        timeout_seconds=SSH_TIMEOUT_SECONDS,
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
