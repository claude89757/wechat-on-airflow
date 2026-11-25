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
from .service import active_subscription_for_venue, record_wechat_incident

LINE = re.compile(
    r"^【(.+)】星期[一二三四五六日]\((\d{2}-\d{2})\)空场[:：]\s*(\d{2}:\d{2})-(\d{2}:\d{2})$"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")


class AvailabilityChanged(ValueError):
    """One well-formed interval no longer has complete current coverage."""


def court_name_matches(advertised: str, observed: str) -> bool:
    """Bind a WeChat line court to an observed slot without digit-suffix collisions.

    Messages often prefix the venue (`大沙河免费场11号场`) while `observed_slots`
    store the short API name (`11号场` / `1号场`). A bare `endswith` also makes
    `…11号场` accept `1号场`, so enqueue/`_prepare` can bind the higher-number
    court to the lower-number event_key and permanently silence the still-free
    court once the wrong key books away.
    """
    advertised_name = str(advertised).strip()
    observed_name = str(observed).strip()
    if not advertised_name or not observed_name:
        return False
    if advertised_name == observed_name:
        return True

    def _suffix_ok(full: str, suffix: str) -> bool:
        if not full.endswith(suffix):
            return False
        cut = len(full) - len(suffix)
        return cut == 0 or not full[cut - 1].isdigit()

    return _suffix_ok(advertised_name, observed_name) or _suffix_ok(
        observed_name, advertised_name
    )


def covered_events(message: str, slots: list[dict[str, Any]]) -> list[str]:
    """Require every advertised interval to be covered by current source slots."""
    result: set[str] = set()
    for line in message.splitlines():
        match = LINE.fullmatch(line.strip())
        if not match:
            raise ValueError("Wechat observation line is invalid")
        court, day, start, end = match.groups()
        if not "00:00" <= start < end <= "24:00" or start[3:] > "59" or end[3:] > "59":
            raise ValueError("Wechat observation interval is invalid")
        if end == "24:00":
            end = "23:59"
        candidates = sorted(
            (
                s
                for s in slots
                if s["booking_date"].strftime("%m-%d") == day
                and court_name_matches(court, s["court_name"])
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
            raise AvailabilityChanged("Wechat availability changed before enqueue")
        result.update(keys)
    if not result:
        raise ValueError("Wechat message has no current availability")
    return sorted(result)


def current_message(message: str, slots: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    """Drop unavailable lines without letting one poison unrelated valid lines.

    Malformed lines remain errors. Never trim a partially covered interval into
    an invented availability interval. Rejected lines can release collector claims.
    """
    retained: list[str] = []
    rejected: list[str] = []
    keys: set[str] = set()
    for line in sorted(set(message.splitlines())):
        line = line.strip()
        try:
            covered = covered_events(line, slots)
        except AvailabilityChanged:
            rejected.append(line)
        else:
            retained.append(line)
            keys.update(covered)
    return "\n".join(retained), sorted(keys), rejected


def _enqueue(payload: dict[str, Any]) -> dict[str, Any]:
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
    # Personal ideal windows narrow email only. Any active venue subscription opens WeChat.
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
        message, keys, rejected = current_message(message, slots)
        if not keys:
            return {
                "success": True,
                "queued": 0,
                "suppressed": True,
                "reason": "availability_changed",
                "rejected_lines": rejected,
            }
        # An early-starting line must not expire later lines in the same digest.
        start_at = max(
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
    return {
        "success": True,
        "queued": len(ids),
        "ids": ids,
        "durable": True,
        "rejected_lines": rejected,
    }


def enqueue(payload: dict[str, Any]) -> dict[str, Any]:
    """Record transport-independent failures without exposing targets or content."""
    venue = str(payload.get("venue_id") or "")
    message = str(payload.get("message") or "").strip()
    receivers = payload.get("receivers")
    groups = [str(r).strip() for r in receivers[:20]] if isinstance(receivers, list) else []
    source = f"enqueue:{venue}"
    try:
        result = _enqueue(payload)
    except Exception as exc:
        if venue in VENUES:
            for receiver in groups:
                record_wechat_incident(
                    source=source,
                    receiver=receiver,
                    message=message,
                    error=RuntimeError(type(exc).__name__),
                    error_code=type(exc).__name__,
                )
        raise
    # A subsequent acknowledged retry resolves only this digest's own incident.
    # A resolution-write failure must not turn an already durable enqueue into failure.
    try:
        with transaction() as connection:
            connection.execute(
                text("""
                UPDATE zacks.wechat_delivery_incidents SET resolved_at=now()
                WHERE source=:source AND message_hash=:message
                  AND receiver_hash=ANY(:receivers) AND resolved_at IS NULL
            """),
                {
                    "source": source,
                    "message": hashlib.sha256(message.encode()).hexdigest(),
                    "receivers": [
                        hashlib.sha256(receiver.encode()).hexdigest() for receiver in groups
                    ],
                },
            )
    except Exception:
        pass
    return result
