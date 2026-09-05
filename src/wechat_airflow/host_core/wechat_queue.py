from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .database import transaction
from .domain import VENUES, utc_now
from .service import active_subscription_for_venue

LINE = re.compile(
    r"^【(.+)】星期[一二三四五六日]\((\d{2}-\d{2})\)空场[:：]\s*(\d{2}:\d{2})-(\d{2}:\d{2})$"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")


def covered_events(message: str, slots: list[dict[str, Any]]) -> list[str]:
    """Require every advertised interval to be covered by current source slots."""
    result: set[str] = set()
    for line in message.splitlines():
        match = LINE.fullmatch(line.strip())
        if not match:
            raise ValueError("Wechat observation line is invalid")
        court, day, start, end = match.groups()
        if end == "24:00":
            end = "23:59"
        candidates = sorted(
            (
                s
                for s in slots
                if s["booking_date"].strftime("%m-%d") == day
                and (court.endswith(str(s["court_name"])) or str(s["court_name"]).endswith(court))
                and s["start_time"] < end
                and s["end_time"] > start
            ),
            key=lambda s: s["start_time"],
        )
        cursor = start
        keys: list[str] = []
        for slot in candidates:
            if slot["start_time"] > cursor:
                break
            cursor = max(cursor, str(slot["end_time"]))
            keys.append(str(slot["event_key"]))
            if cursor >= end:
                break
        if cursor < end:
            raise ValueError("Wechat availability changed before enqueue")
        result.update(keys)
    if not result:
        raise ValueError("Wechat message has no current availability")
    return sorted(result)


def enqueue(payload: dict[str, Any]) -> dict[str, Any]:
    venue = str(payload.get("venue_id") or "")
    message = str(payload.get("message") or "").strip()
    device = str(payload.get("device_name") or "").strip()
    receivers = payload.get("receivers")
    if (
        venue not in VENUES
        or not device
        or len(device) > 128
        or not message
        or len(message) > 20000
        or not isinstance(receivers, list)
        or not 1 <= len(receivers) <= 20
    ):
        raise ValueError("Wechat enqueue payload is invalid")
    groups = list(dict.fromkeys(str(r).strip() for r in receivers))
    if any(not r or len(r) > 256 for r in groups):
        raise ValueError("Wechat receiver is invalid")
    if not active_subscription_for_venue(venue):
        return {
            "success": True,
            "queued": 0,
            "suppressed": True,
            "reason": "no_active_subscription",
        }
    now = utc_now()
    with transaction() as connection:
        slots = [
            dict(r)
            for r in connection.execute(
                text("""
            SELECT s.* FROM zacks.observed_slots s
            WHERE s.venue_id = :venue AND EXISTS(
                SELECT 1 FROM zacks.current_availability c WHERE c.event_key = s.event_key
                AND c.last_seen_at > now() - interval '15 minutes')
              AND (s.booking_date + CAST(s.start_time AS time)) AT TIME ZONE 'Asia/Shanghai' > now()
        """),
                {"venue": venue},
            ).mappings()
        ]
        keys = covered_events(message, slots)
        start_at = min(
            datetime.combine(
                s["booking_date"], datetime.strptime(s["start_time"], "%H:%M").time(), SHANGHAI
            )
            for s in slots
            if s["event_key"] in keys
        )
        expires = min(now + timedelta(minutes=5), start_at)
        ids = []
        for receiver in groups:
            key = hashlib.sha256(
                "\0".join([venue, receiver, device, message, *keys]).encode()
            ).hexdigest()
            connection.execute(
                text("""
                INSERT INTO zacks.wechat_outbox(id, venue_id, receiver, device_name, source,
                    message, event_keys, expires_at)
                VALUES (:id, :venue, :receiver, :device, :source, :message, CAST(:keys AS jsonb), :expires)
                ON CONFLICT(id) DO NOTHING
            """),
                {
                    "id": key,
                    "venue": venue,
                    "receiver": receiver,
                    "device": device,
                    "source": str(payload.get("source") or "unknown")[:120],
                    "message": message,
                    "keys": json.dumps(keys),
                    "expires": expires,
                },
            )
            ids.append(key)
    return {"success": True, "queued": len(ids), "ids": ids, "durable": True}
