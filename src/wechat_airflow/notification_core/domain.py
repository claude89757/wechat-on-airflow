from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class NormalizedSlot:
    booking_date: date
    court_name: str
    start_minute: int
    end_minute: int

    @property
    def event_key(self) -> str:
        canonical = "|".join(
            (
                self.booking_date.isoformat(),
                self.court_name,
                minute_text(self.start_minute),
                minute_text(self.end_minute),
            )
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NormalizedObservation:
    venue_id: str
    venue_name: str
    healthy: bool
    checked_at: datetime
    error: str | None
    slots: tuple[NormalizedSlot, ...]
    fingerprint: str


@dataclass(frozen=True)
class SubscriptionSnapshot:
    subscription_id: str
    email: str
    venue_ids: tuple[str, ...]
    weekday_mask: int
    start_minute: int
    end_minute: int
    tier: str
    auto_renew: bool
    active_until: datetime
    updated_at: datetime


def _field(mapping: Mapping[str, object], *names: str) -> object | None:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _required_text(mapping: Mapping[str, object], *names: str) -> str:
    value = str(_field(mapping, *names) or "").strip()
    if not value:
        raise ValueError(f"missing required field: {names[0]}")
    return value


def parse_datetime(value: object, *, field: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def parse_minute(value: object, *, allow_2400: bool = False) -> int:
    raw = str(value or "").strip()
    if allow_2400 and raw == "24:00":
        return 24 * 60
    if len(raw) != 5 or raw[2] != ":":
        raise ValueError("time must use HH:MM")
    try:
        hour = int(raw[:2])
        minute = int(raw[3:])
    except ValueError as exc:
        raise ValueError("time must use HH:MM") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("time is outside the valid range")
    return hour * 60 + minute


def minute_text(value: int) -> str:
    if value == 24 * 60:
        return "24:00"
    return f"{value // 60:02d}:{value % 60:02d}"


def weekday_mask_from_value(value: object) -> int:
    if isinstance(value, int):
        if 0 <= value <= 127:
            return value
        raise ValueError("weekday_mask is outside the valid range")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return 127
    mask = 0
    for item in value:
        day = int(item)
        if day < 1 or day > 7:
            raise ValueError("weekday must be between 1 and 7")
        mask |= 1 << (day - 1)
    return mask or 127


def slot_matches_subscription(
    slot: NormalizedSlot,
    *,
    weekday_mask: int,
    start_minute: int,
    end_minute: int,
) -> bool:
    weekday_bit = 1 << (slot.booking_date.isoweekday() - 1)
    if weekday_mask & weekday_bit == 0:
        return False
    return max(slot.start_minute, start_minute) < min(slot.end_minute, end_minute)


def _normalize_slot(value: object) -> NormalizedSlot:
    if not isinstance(value, Mapping):
        raise ValueError("slot must be an object")
    candidate = {str(key): item for key, item in value.items()}
    booking_date = date.fromisoformat(_required_text(candidate, "date", "booking_date"))
    court_name = _required_text(candidate, "court_name", "courtName")[:160]
    start_minute = parse_minute(_field(candidate, "start_time", "startTime"))
    end_minute = parse_minute(
        _field(candidate, "end_time", "endTime"),
        allow_2400=True,
    )
    if end_minute <= start_minute:
        raise ValueError("slot end time must be after start time")
    return NormalizedSlot(
        booking_date=booking_date,
        court_name=court_name,
        start_minute=start_minute,
        end_minute=end_minute,
    )


def normalize_observation(payload: object) -> NormalizedObservation:
    if not isinstance(payload, Mapping):
        raise ValueError("observation payload must be an object")
    candidate = {str(key): value for key, value in payload.items()}
    venue_id = _required_text(candidate, "venue_id", "venueId")[:80]
    venue_name = _required_text(candidate, "venue_name", "venueName")[:160]
    checked_at = parse_datetime(
        _field(candidate, "checked_at", "checkedAt"),
        field="checked_at",
    )
    healthy = _field(candidate, "healthy") is True
    error_value = str(_field(candidate, "error") or "").strip()
    raw_slots = _field(candidate, "slots")
    if raw_slots is None:
        raw_slots = []
    if not isinstance(raw_slots, Sequence) or isinstance(raw_slots, (str, bytes, bytearray)):
        raise ValueError("slots must be an array")

    deduplicated: dict[str, NormalizedSlot] = {}
    for raw_slot in raw_slots[:500]:
        slot = _normalize_slot(raw_slot)
        deduplicated[slot.event_key] = slot
    slots = tuple(deduplicated[key] for key in sorted(deduplicated))

    canonical = {
        "venue_id": venue_id,
        "venue_name": venue_name,
        "healthy": healthy,
        "error": error_value[:300] or None,
        "slots": [
            {
                "date": slot.booking_date.isoformat(),
                "court_name": slot.court_name,
                "start_time": minute_text(slot.start_minute),
                "end_time": minute_text(slot.end_minute),
            }
            for slot in slots
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return NormalizedObservation(
        venue_id=venue_id,
        venue_name=venue_name,
        healthy=healthy,
        checked_at=checked_at,
        error=error_value[:300] or None,
        slots=slots,
        fingerprint=fingerprint,
    )


def normalize_subscription(value: object) -> SubscriptionSnapshot:
    if not isinstance(value, Mapping):
        raise ValueError("subscription must be an object")
    candidate = {str(key): item for key, item in value.items()}
    raw_venues = _field(candidate, "venue_ids", "venueIds")
    if isinstance(raw_venues, str):
        try:
            raw_venues = json.loads(raw_venues)
        except json.JSONDecodeError as exc:
            raise ValueError("venue_ids must be valid JSON") from exc
    if not isinstance(raw_venues, Sequence) or isinstance(
        raw_venues, (str, bytes, bytearray)
    ):
        raise ValueError("venue_ids must be an array")
    venue_ids = tuple(
        dict.fromkeys(str(item).strip() for item in raw_venues if str(item).strip())
    )
    if not venue_ids:
        raise ValueError("subscription must include at least one venue")

    tier = str(_field(candidate, "tier") or "standard").strip().lower()
    if tier not in {"standard", "priority"}:
        tier = "standard"
    return SubscriptionSnapshot(
        subscription_id=_required_text(candidate, "id", "subscription_id")[:120],
        email=_required_text(candidate, "email").lower()[:320],
        venue_ids=venue_ids,
        weekday_mask=weekday_mask_from_value(
            _field(candidate, "weekday_mask", "weekdayMask", "weekdays")
        ),
        start_minute=parse_minute(_field(candidate, "start_time", "startTime")),
        end_minute=parse_minute(
            _field(candidate, "end_time", "endTime"), allow_2400=True
        ),
        tier=tier,
        auto_renew=_field(candidate, "auto_renew", "autoRenew") is True,
        active_until=parse_datetime(
            _field(candidate, "active_until", "activeUntil"),
            field="active_until",
        ),
        updated_at=parse_datetime(
            _field(candidate, "updated_at", "updatedAt", "created_at", "createdAt"),
            field="updated_at",
        ),
    )


def format_slot_line(venue_name: str, slot: NormalizedSlot) -> str:
    weekday = "一二三四五六日"[slot.booking_date.isoweekday() - 1]
    return (
        f"【{venue_name}】星期{weekday}({slot.booking_date.strftime('%m-%d')})空场: "
        f"{minute_text(slot.start_minute)}-{minute_text(slot.end_minute)}"
    )
