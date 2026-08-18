"""Append booking mini-program links to WeChat alerts without repeating them."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

BOOKING_LINK_LAST_SENT_VAR = "WECHAT_BOOKING_LINK_LAST_SENT"
BOOKING_LINK_COOLDOWN = timedelta(hours=2)


@dataclass(frozen=True)
class BookingMiniProgram:
    program_id: str
    link: str


WEILAIHUI = BookingMiniProgram(
    program_id="weilaihui",
    link="#小程序://未来荟/XL8wsbG5boBuZSl",
)
SYSH_PROGRAM = BookingMiniProgram(
    program_id="sysh",
    link="#小程序://上越网球中心-沙河店/mug6ErSFWCSdvvc",
)
TOPS_PROGRAM = BookingMiniProgram(
    program_id="tops",
    link="#小程序://Tops网球/lo2x6SO0XGpdUph",
)
JDWX_PROGRAM = BookingMiniProgram(
    program_id="jdwx",
    link="#小程序://ing在运动/8EnsqtWMGoMe6Kr",
)
DSH_FREE_PROGRAM = BookingMiniProgram(
    program_id="dsh_free",
    link="#小程序://南山文体通/C28W6ASVGvL4usz",
)
TYZX_PROGRAM = BookingMiniProgram(
    program_id="tyzx",
    link="#小程序://i深体/GA0nZbyQSAq9iSa",
)

VENUE_BOOKING_PROGRAMS: Mapping[str, BookingMiniProgram] = {
    "szw": WEILAIHUI,
    "gba": WEILAIHUI,
    "sysh": SYSH_PROGRAM,
    "tops": TOPS_PROGRAM,
    "jdwx": JDWX_PROGRAM,
    "dsh_free": DSH_FREE_PROGRAM,
    "tyzx": TYZX_PROGRAM,
}

BookingLinkCache = dict[str, dict[str, str]]


@dataclass(frozen=True)
class BookingLinkPlan:
    message: str
    cache: BookingLinkCache | None
    program_id: str | None
    previous_timestamp: str | None


def program_for_venue(venue_id: str | None) -> BookingMiniProgram | None:
    if venue_id is None:
        return None
    normalized = venue_id.strip()
    if not normalized:
        return None
    return VENUE_BOOKING_PROGRAMS.get(normalized)


def attach_footer(message: str, link: str) -> str:
    stripped = message.strip()
    if not stripped:
        return link
    if link in stripped:
        return stripped
    return f"{stripped}\n\n{link}"


def _as_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _as_naive(parsed)


def is_cooling_down(
    last_sent: datetime | None,
    now: datetime,
    cooldown: timedelta = BOOKING_LINK_COOLDOWN,
) -> bool:
    if last_sent is None:
        return False
    return _as_naive(now) - last_sent < cooldown


def normalize_cache(cache: object) -> BookingLinkCache:
    normalized: BookingLinkCache = {}
    if not isinstance(cache, dict):
        return normalized
    for receiver, programs in cache.items():
        if not isinstance(receiver, str) or not receiver.strip():
            continue
        if not isinstance(programs, dict):
            continue
        timestamps = {
            program_id: timestamp
            for program_id, timestamp in programs.items()
            if isinstance(program_id, str)
            and program_id.strip()
            and isinstance(timestamp, str)
            and timestamp.strip()
        }
        if timestamps:
            normalized[receiver] = timestamps
    return normalized


def last_sent_at(cache: object, receiver: str, program_id: str) -> datetime | None:
    programs = normalize_cache(cache).get(receiver)
    if programs is None:
        return None
    return parse_timestamp(programs.get(program_id))


def previous_timestamp(cache: object, receiver: str, program_id: str) -> str | None:
    programs = normalize_cache(cache).get(receiver)
    if programs is None:
        return None
    raw = programs.get(program_id)
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw


def mark_sent(
    cache: object,
    receiver: str,
    program_id: str,
    sent_at: datetime,
) -> BookingLinkCache:
    updated = normalize_cache(cache)
    chat_entry = dict(updated.get(receiver, {}))
    chat_entry[program_id] = _as_naive(sent_at).isoformat(timespec="seconds")
    updated[receiver] = chat_entry
    return updated


def restore_sent(
    cache: object,
    receiver: str,
    program_id: str,
    previous: str | None,
) -> BookingLinkCache:
    updated = normalize_cache(cache)
    chat_entry = dict(updated.get(receiver, {}))
    if previous is None:
        chat_entry.pop(program_id, None)
    else:
        chat_entry[program_id] = previous
    if chat_entry:
        updated[receiver] = chat_entry
    else:
        updated.pop(receiver, None)
    return updated


def plan_booking_link(
    message: str,
    *,
    receiver: str,
    venue_id: str | None,
    cache: object,
    now: datetime,
    cooldown: timedelta = BOOKING_LINK_COOLDOWN,
) -> BookingLinkPlan:
    program = program_for_venue(venue_id)
    if program is None:
        return BookingLinkPlan(
            message=message, cache=None, program_id=None, previous_timestamp=None
        )

    last_sent = last_sent_at(cache, receiver, program.program_id)
    if is_cooling_down(last_sent, now, cooldown):
        return BookingLinkPlan(
            message=message,
            cache=None,
            program_id=program.program_id,
            previous_timestamp=None,
        )

    previous = previous_timestamp(cache, receiver, program.program_id)
    return BookingLinkPlan(
        message=attach_footer(message, program.link),
        cache=mark_sent(cache, receiver, program.program_id, now),
        program_id=program.program_id,
        previous_timestamp=previous,
    )
