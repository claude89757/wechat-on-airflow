from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken

SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
EMAIL_PATTERN: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TIME_PATTERN: Final = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
UUID_PATTERN: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
ALL_WEEKDAY_MASK: Final = 127

VENUES: Final[dict[str, str]] = {
    "szw": "深圳湾",
    "gba": "大湾区网球场",
    "dsh_free": "大沙河免费场",
    "dsh": "大沙河国际网球中心",
    "baoti": "宝安网球中心",
    "sysh": "上越沙河",
    "tops": "TOPS 科技园",
    "fsb": "泛思博特福中福",
    "fsb_shenyun": "泛思博特深云",
    "fsb_shekou": "泛思博特蛇口",
    "fsb_xinan": "泛思博特新安",
    "fsb_zhengzhong": "泛思博特正中",
    "fsb_atuoshan": "泛思博特安托山",
    "fsb_zonglvquan": "泛思博特棕榈泉",
    "fsb_guanhu": "泛思博特观湖",
    "fsb_bantian": "泛思博特坂田",
    "fsb_shahe": "泛思博特沙河",
    "fsb_baoshui": "泛思博特保税",
    "fsb_nanyou": "泛思博特南油",
    "fsb_xinqiao": "泛思博特新桥",
    "fsb_yifangcheng": "泛思博特壹方城",
    "fsb_qilin": "泛思博特麒麟",
    "fsb_maozhouhe": "泛思博特茅洲河",
    "fft_qianhai": "FFTENNIS前海国际网球中心",
    "ppba": "PICKLE POP宝安",
    "tyzx": "深圳市体育中心",
    "jdwx": "金地威新",
}

STANDARD_TERMS: Final = tuple(f"{days}d" for days in range(7, 15))
PRIORITY_TERMS: Final = (*STANDARD_TERMS, "30d", "90d", "180d", "long_term")
TERM_DAYS: Final = {
    "7d": 7,
    "8d": 8,
    "9d": 9,
    "10d": 10,
    "11d": 11,
    "12d": 12,
    "13d": 13,
    "14d": 14,
    "30d": 30,
    "90d": 90,
    "180d": 180,
}
LONG_TERM_LEASE_DAYS: Final = 90
LONG_TERM_RENEW_THRESHOLD_DAYS: Final = 45

INVITE_PREFIX: Final = "ACE"
INVITE_ALPHABET: Final = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
INVITE_SCENES: Final = (
    "SUNNY",
    "BREEZY",
    "CLOUD",
    "MOON",
    "STAR",
    "COMET",
    "AURORA",
    "OCEAN",
    "RIVER",
    "WAVE",
    "TIDE",
    "CORAL",
    "FOREST",
    "CEDAR",
    "MAPLE",
    "BAMBOO",
    "MEADOW",
    "GARDEN",
    "BLOOM",
    "PEACH",
    "MANGO",
    "LEMON",
    "BERRY",
    "COCOA",
    "HONEY",
    "MINT",
    "LATTE",
    "MOCHI",
    "COOKIE",
    "JELLY",
    "SUGAR",
    "SPICE",
    "RALLY",
    "SERVE",
    "VOLLEY",
    "SMASH",
    "SLICE",
    "SPIN",
    "LOB",
    "COURT",
    "NET",
    "BASELINE",
    "MATCH",
    "SET",
    "GAME",
    "BREAK",
    "FLASH",
    "TURBO",
    "ROCKET",
    "NOVA",
    "PIXEL",
    "NEON",
    "MAGIC",
    "LUCKY",
    "HAPPY",
    "BRAVE",
    "QUICK",
    "CHILL",
    "GLOW",
    "DREAM",
    "PARTY",
    "FIESTA",
    "SUNSET",
    "SUNRISE",
)
INVITE_MASCOTS: Final = (
    "PANDA",
    "OTTER",
    "TIGER",
    "LION",
    "FOX",
    "WOLF",
    "BEAR",
    "KOALA",
    "RABBIT",
    "BUNNY",
    "DEER",
    "MOOSE",
    "HORSE",
    "ZEBRA",
    "CAMEL",
    "LLAMA",
    "ALPACA",
    "MONKEY",
    "LEMUR",
    "SLOTH",
    "BADGER",
    "BEAVER",
    "FERRET",
    "HEDGEHOG",
    "RACCOON",
    "SEAL",
    "DOLPHIN",
    "WHALE",
    "SHARK",
    "TURTLE",
    "PENGUIN",
    "PUFFIN",
    "EAGLE",
    "FALCON",
    "OWL",
    "ROBIN",
    "SPARROW",
    "PARROT",
    "TOUCAN",
    "SWAN",
    "DUCK",
    "GOOSE",
    "CRANE",
    "HERON",
    "FLAMINGO",
    "PEACOCK",
    "GECKO",
    "IGUANA",
    "COBRA",
    "DRAGON",
    "PHOENIX",
    "UNICORN",
    "KITTEN",
    "PUPPY",
    "HAMSTER",
    "CHINCHILLA",
    "BISON",
    "YAK",
    "ANT",
    "BEE",
    "BUTTERFLY",
    "FIREFLY",
    "LADYBUG",
    "MANTIS",
)


@dataclass(frozen=True)
class SlotObservation:
    booking_date: date
    court_name: str
    start_time: str
    end_time: str

    def as_public_dict(self) -> dict[str, str]:
        return {
            "date": self.booking_date.isoformat(),
            "court_name": self.court_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


@dataclass(frozen=True)
class VenueObservation:
    venue_id: str
    venue_name: str
    observation_scope: str
    healthy: bool
    checked_at: datetime
    error: str | None
    slots: tuple[SlotObservation, ...]


@dataclass(frozen=True)
class SubscriptionInput:
    venue_ids: tuple[str, ...]
    weekdays: tuple[int, ...]
    start_time: str
    end_time: str
    term_code: str


@dataclass(frozen=True)
class ResolvedTerm:
    term_code: str
    duration_days: int
    auto_renew: bool
    active_until: datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_email(value: object) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("请输入有效的邮箱地址")
    return email


def mask_email(email: str) -> str:
    local, domain = email.split("@", 1)
    visible_length = min(2, len(local)) if len(local) > 1 else len(local)
    return f"{local[:visible_length]}{'*' * max(3, len(local) - visible_length)}@{domain}"


def parse_time(value: object) -> int:
    normalized = str(value or "")
    if not TIME_PATTERN.fullmatch(normalized):
        raise ValueError("时间格式无效")
    hour, minute = (int(part) for part in normalized.split(":", 1))
    return hour * 60 + minute


def normalize_weekdays(value: object) -> tuple[int, ...]:
    if value is None:
        return tuple(range(1, 8))
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("请至少选择一个星期")
    parsed: set[int] = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            raise ValueError("星期选择无效")
        try:
            parsed.add(int(item))
        except ValueError as exc:
            raise ValueError("星期选择无效") from exc
    weekdays = tuple(sorted(parsed))
    if not weekdays or any(item < 1 or item > 7 for item in weekdays):
        raise ValueError("星期选择无效")
    return weekdays


def weekday_mask(weekdays: Iterable[int]) -> int:
    mask = 0
    for weekday in weekdays:
        if weekday < 1 or weekday > 7:
            raise ValueError("星期选择无效")
        mask |= 1 << (weekday - 1)
    if mask == 0:
        raise ValueError("请至少选择一个星期")
    return mask


def weekdays_from_mask(value: object) -> list[int]:
    mask = ALL_WEEKDAY_MASK
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        try:
            mask = int(value)
        except ValueError:
            mask = ALL_WEEKDAY_MASK
    if mask < 1 or mask > ALL_WEEKDAY_MASK:
        mask = ALL_WEEKDAY_MASK
    return [weekday for weekday in range(1, 8) if mask & (1 << (weekday - 1))]


@dataclass(frozen=True)
class IdealWindow:
    """One named product preset stored as the existing single window."""

    preset_id: str
    label: str
    weekdays: tuple[int, ...]
    start_time: str
    end_time: str


# MVP keeps one continuous window per subscription. A later phase can add
# time_windows jsonb; these presets must remain expressible as weekday_mask
# plus start_time/end_time so existing rows need no migration.
IDEAL_WINDOWS: Final[tuple[IdealWindow, ...]] = (
    IdealWindow("weekday_evening", "下班后打球", (1, 2, 3, 4, 5), "19:00", "22:00"),
    IdealWindow("weekday_noon", "午休局", (1, 2, 3, 4, 5), "12:00", "14:00"),
    IdealWindow("weekend_morning", "周末上午", (6, 7), "08:00", "12:00"),
    IdealWindow("weekend_afternoon", "周末下午", (6, 7), "14:00", "18:00"),
)
IDEAL_WINDOWS_BY_ID: Final[dict[str, IdealWindow]] = {
    window.preset_id: window for window in IDEAL_WINDOWS
}
CUSTOM_PREFERENCE: Final = "custom"
CUSTOM_PREFERENCE_LABEL: Final = "自定义"
SUBSCRIBER_DIGEST_NOTE: Final = (
    "这些空场与你订阅的理想时段有交叠。微信群消息仍按场地发送，不按个人时段过滤。"
)


def describe_preference(weekdays: Iterable[int], start_time: str, end_time: str) -> tuple[str, str]:
    """Label a stored window. NULL/unknown history is custom; exact presets match."""
    normalized = tuple(sorted(int(day) for day in weekdays))
    for window in IDEAL_WINDOWS:
        if (
            window.weekdays == normalized
            and window.start_time == start_time
            and window.end_time == end_time
        ):
            return window.preset_id, window.label
    return CUSTOM_PREFERENCE, CUSTOM_PREFERENCE_LABEL


def resolve_subscription_window(value: Mapping[Any, Any]) -> tuple[tuple[int, ...], str, str]:
    """Map an optional preferencePreset onto the existing weekday and clock fields.

    Omitting the preset preserves legacy clients. A named preset may be sent
    alone, or together with the same canonical weekdays and clock. Custom and
    legacy payloads keep explicit start/end; missing weekdays still mean every day.
    """
    raw_preset = value.get("preferencePreset", value.get("preference_preset"))
    if raw_preset in (None, ""):
        preset_id = ""
    elif isinstance(raw_preset, str):
        preset_id = raw_preset.strip()
    else:
        raise ValueError("理想时段预设无效")

    window: IdealWindow | None
    if preset_id in ("", CUSTOM_PREFERENCE):
        window = None
    else:
        window = IDEAL_WINDOWS_BY_ID.get(preset_id)
        if window is None:
            raise ValueError("理想时段预设无效")

    raw_start = value.get("startTime", value.get("start_time"))
    raw_end = value.get("endTime", value.get("end_time"))
    has_weekdays = value.get("weekdays") is not None
    has_start = raw_start not in (None, "")
    has_end = raw_end not in (None, "")
    if window is not None and (has_weekdays or has_start or has_end):
        if not (has_weekdays and has_start and has_end):
            raise ValueError("理想时段与所选星期或时刻不一致")
    if window is not None and not (has_weekdays or has_start or has_end):
        return window.weekdays, window.start_time, window.end_time

    start_time = str(raw_start or "")
    end_time = str(raw_end or "")
    if parse_time(start_time) >= parse_time(end_time):
        raise ValueError("结束时间必须晚于开始时间")
    weekdays = normalize_weekdays(value.get("weekdays"))
    if window is not None and (
        weekdays != window.weekdays
        or start_time != window.start_time
        or end_time != window.end_time
    ):
        raise ValueError("理想时段与所选星期或时刻不一致")
    return weekdays, start_time, end_time


def with_subscriber_digest_note(body: str) -> str:
    """Append the channel note once, without turning it into another slot line."""
    if SUBSCRIBER_DIGEST_NOTE in body:
        return body
    return f"{body}\n\n{SUBSCRIBER_DIGEST_NOTE}"


def validate_subscription(value: object, *, priority: bool) -> SubscriptionInput:
    if not isinstance(value, Mapping):
        raise ValueError("订阅参数无效")
    raw_venues = value.get("venueIds")
    if not isinstance(raw_venues, Sequence) or isinstance(raw_venues, (str, bytes)):
        raise ValueError("请至少选择一个场地")
    venue_ids = tuple(sorted({str(item).strip() for item in raw_venues}))
    if (
        not venue_ids
        or len(venue_ids) != len(raw_venues)
        or any(item not in VENUES for item in venue_ids)
    ):
        raise ValueError("场地选择无效")
    weekdays, start_time, end_time = resolve_subscription_window(value)
    raw_term = str(value.get("termCode") or "").strip().lower()
    if not raw_term:
        try:
            raw_term = f"{int(value.get('durationDays') or 7)}d"
        except (TypeError, ValueError):
            raw_term = "7d"
    allowed = PRIORITY_TERMS if priority else STANDARD_TERMS
    if raw_term not in allowed:
        raise ValueError(
            "该订阅有效期仅限优先用户" if raw_term in PRIORITY_TERMS else "订阅有效期无效"
        )
    return SubscriptionInput(venue_ids, weekdays, start_time, end_time, raw_term)


def resolve_term(term_code: str, now: datetime | None = None) -> ResolvedTerm:
    current = (now or utc_now()).astimezone(UTC)
    if term_code == "long_term":
        return ResolvedTerm(term_code, 0, True, current + timedelta(days=LONG_TERM_LEASE_DAYS))
    days = TERM_DAYS.get(term_code)
    if days is None:
        raise ValueError("订阅有效期无效")
    return ResolvedTerm(term_code, days, False, current + timedelta(days=days))


def validate_slot(value: object) -> SlotObservation:
    if not isinstance(value, Mapping):
        raise ValueError("场地数据无效")
    raw_date = str(value.get("date") or "")
    court_name = str(value.get("court_name") or value.get("courtName") or "").strip()
    start_time = str(value.get("start_time") or value.get("startTime") or "")
    end_time = str(value.get("end_time") or value.get("endTime") or "")
    try:
        booking_date = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise ValueError("场地数据无效") from exc
    if not court_name or len(court_name) > 100:
        raise ValueError("场地数据无效")
    if parse_time(start_time) >= parse_time(end_time):
        raise ValueError("场地时段无效")
    return SlotObservation(booking_date, court_name, start_time, end_time)


def validate_observation(value: object) -> VenueObservation:
    if not isinstance(value, Mapping):
        raise ValueError("场地数据无效")
    venue_id = str(value.get("venue_id") or value.get("venueId") or "").strip()
    if venue_id not in VENUES:
        raise ValueError("场地数据无效")
    venue_name = str(value.get("venue_name") or value.get("venueName") or VENUES[venue_id]).strip()
    scope = str(
        value.get("observation_scope") or value.get("observationScope") or "default"
    ).strip()[:120]
    healthy = value.get("healthy") is True
    raw_checked = value.get("checked_at") or value.get("checkedAt")
    try:
        checked_at = datetime.fromisoformat(str(raw_checked).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        checked_at = utc_now()
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=UTC)
    raw_slots = value.get("slots")
    slots = tuple(validate_slot(item) for item in raw_slots) if isinstance(raw_slots, list) else ()
    unique = {slot_event_key(venue_id, slot): slot for slot in slots}
    error = str(value.get("error") or "").strip()[:300] or None
    return VenueObservation(
        venue_id=venue_id,
        venue_name=venue_name[:100],
        observation_scope=scope or "default",
        healthy=healthy,
        checked_at=checked_at.astimezone(UTC),
        error=error,
        slots=tuple(unique[key] for key in sorted(unique)),
    )


def observation_fingerprint(observation: VenueObservation) -> str:
    canonical = {
        "venue_id": observation.venue_id,
        "venue_name": observation.venue_name,
        "scope": observation.observation_scope,
        "healthy": observation.healthy,
        "error": observation.error,
        "slots": [slot.as_public_dict() for slot in observation.slots],
    }
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def slot_event_key(venue_id: str, slot: SlotObservation) -> str:
    return hashlib.sha256(
        "|".join(
            [
                venue_id,
                slot.booking_date.isoformat(),
                slot.court_name,
                slot.start_time,
                slot.end_time,
            ]
        ).encode()
    ).hexdigest()


def slot_matches(
    slot: SlotObservation, *, weekday_mask_value: int, start_time: str, end_time: str
) -> bool:
    weekday = slot.booking_date.isoweekday()
    return bool(weekday_mask_value & (1 << (weekday - 1))) and (
        parse_time(slot.start_time) < parse_time(end_time)
        and parse_time(slot.end_time) > parse_time(start_time)
    )


def format_slot_line(venue_name: str, slot: SlotObservation) -> str:
    weekday = "一二三四五六日"[slot.booking_date.isoweekday() - 1]
    location = (
        slot.court_name
        if slot.court_name.startswith(venue_name)
        else f"{venue_name}{slot.court_name}"
    )
    return (
        f"{location} {slot.booking_date.strftime('%m-%d')} 星期{weekday} "
        f"{slot.start_time}-{slot.end_time}"
    )


def format_digest(lines: Iterable[str]) -> tuple[str, str]:
    unique = list(dict.fromkeys(line.strip() for line in lines if line.strip()))
    if not unique:
        raise ValueError("通知内容为空")
    subject = unique[0] if len(unique) == 1 else f"{unique[0]} 等 {len(unique)} 个时段"
    return subject, "\n".join(unique)


def subscription_dedupe_key(
    email: str,
    venue_ids: Iterable[str],
    start_time: str,
    end_time: str,
    weekday_mask_value: int,
) -> str:
    return hashlib.sha256(
        "|".join(
            [email, ",".join(sorted(venue_ids)), start_time, end_time, str(weekday_mask_value)]
        ).encode()
    ).hexdigest()


def random_token(byte_length: int = 32) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(byte_length)).decode().rstrip("=")


def random_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_verification_code(challenge_id: str, code: str, pepper: str) -> str:
    return hashlib.sha256(f"{challenge_id}:{code}:{pepper}".encode()).hexdigest()


def normalize_invite_code(value: object) -> str:
    parts = [part for part in re.split(r"[^A-Z0-9]+", str(value or "").upper().strip()) if part]
    if (
        len(parts) != 4
        or parts[0] != INVITE_PREFIX
        or parts[1] not in INVITE_SCENES
        or parts[2] not in INVITE_MASCOTS
        or len(parts[3]) != 6
        or any(character not in INVITE_ALPHABET for character in parts[3])
    ):
        raise ValueError("邀请码格式无效")
    return "-".join(parts)


def generate_invite_code() -> str:
    suffix = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(6))
    return (
        f"{INVITE_PREFIX}-{secrets.choice(INVITE_SCENES)}-{secrets.choice(INVITE_MASCOTS)}-{suffix}"
    )


def hash_invite_code(code: object, pepper: str) -> str:
    normalized = normalize_invite_code(code)
    return hmac.new(pepper.encode(), normalized.encode(), hashlib.sha256).hexdigest()


def _fernet(pepper: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(f"zacks-invite:{pepper}".encode()).digest())
    return Fernet(key)


def encrypt_invite_code(code: str, pepper: str) -> str:
    return _fernet(pepper).encrypt(normalize_invite_code(code).encode()).decode()


def decrypt_invite_code(ciphertext: str | None, pepper: str) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet(pepper).decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())


def jsonable_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)
