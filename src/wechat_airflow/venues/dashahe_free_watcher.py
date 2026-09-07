from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from wechat_airflow.notifications.webapp import publish_venue_observation
from wechat_airflow.notifications.wechat import send_wechat_text_to_chatrooms_best_effort
from wechat_airflow.venues.nswtt_client import NswttClient, NswttConfig

CONFIG_VARIABLE = "NSWTT_API_CONFIG"
CACHE_KEY = "大沙河免费场"
VENUE_ID = "dsh_free"
VENUE_NAME = "大沙河免费场"
DAG_ID = "大沙河免费场巡检"
WECHAT_CHATROOMS = ("Zacks_大沙河限定免费",)
MAX_SUBSCRIPTION_DAYS = 14
SHANGHAI = ZoneInfo("Asia/Shanghai")


class NswttProtocolError(ValueError):
    """A missing/malformed collection is not evidence of an empty venue."""


def _rows(data: object, *names: str) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise NswttProtocolError("NSWTT data must be an object")
    for name in names:
        if name in data:
            value = data[name]
            if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
                raise NswttProtocolError("NSWTT collection must be a list of objects")
            return cast(list[dict[str, Any]], value)
    raise NswttProtocolError("NSWTT collection is missing")


def future_slots(
    slots: list[dict[str, str]], *, now: datetime | None = None
) -> list[dict[str, str]]:
    instant = now or datetime.now(SHANGHAI)
    if instant.tzinfo is None:
        raise ValueError("now must include a timezone")
    return [
        slot
        for slot in slots
        if datetime.fromisoformat(f"{slot['date']}T{slot['start_time']}").replace(tzinfo=SHANGHAI)
        > instant
    ]


TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _load_config_value() -> object:
    from airflow.sdk import Variable

    return Variable.get(CONFIG_VARIABLE, deserialize_json=True)


def _load_cache() -> list[str]:
    from airflow.sdk import Variable

    missing = object()
    cache = Variable.get(CACHE_KEY, deserialize_json=True, default=missing)
    if cache is missing:
        _store_cache([])
        return []
    if not isinstance(cache, list):
        return []
    return [str(item) for item in cache if str(item).strip()]


def _store_cache(cache: list[str]) -> None:
    from airflow.sdk import Variable

    Variable.set(
        key=CACHE_KEY,
        value=cache[-100:],
        description=f"{VENUE_NAME}场地通知 - 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        serialize_json=True,
    )


def format_wechat_messages(slots: list[dict[str, str]]) -> list[str]:
    messages: list[str] = []
    for slot in slots:
        try:
            date_obj = date.fromisoformat(slot["date"])
        except ValueError:
            continue
        weekday_str = ["一", "二", "三", "四", "五", "六", "日"][date_obj.weekday()]
        inform_date = date_obj.strftime("%m-%d")
        court_name = str(slot.get("court_name") or "").strip()
        start_time = str(slot.get("start_time") or "").strip()
        end_time = str(slot.get("end_time") or "").strip()
        if not court_name or not start_time or not end_time:
            continue
        messages.append(
            f"【{VENUE_NAME}{court_name}】星期{weekday_str}({inform_date})空场: {start_time}-{end_time}"
        )
    return messages


def ready_free_dates(
    calendar_data: object,
    *,
    today: date | None = None,
) -> list[str]:
    rows = _rows(calendar_data, "list")
    current_date = today or datetime.now(SHANGHAI).date()
    last_date = current_date + timedelta(days=MAX_SUBSCRIPTION_DAYS)
    ready: list[str] = []
    for row in rows:
        try:
            booking_date = date.fromisoformat(str(row.get("slicedate") or ""))
        except ValueError:
            continue
        if not current_date <= booking_date <= last_date:
            continue
        try:
            sale_ready = all(
                int(row.get(field) or 0) == 200 for field in ("status", "openstatus", "issale")
            )
        except (TypeError, ValueError):
            sale_ready = False
        if sale_ready:
            ready.append(booking_date.isoformat())
    return sorted(set(ready))


def _slice_is_free(slot: dict[str, Any]) -> bool:
    try:
        available = int(slot.get("status") or 0) == 200
    except (TypeError, ValueError):
        available = False
    if not available:
        return False
    price_fields = ("finalunitpricey", "unitpricey", "finalunitprice", "unitprice")
    for field in price_fields:
        if slot.get(field) in (None, ""):
            continue
        try:
            if float(slot[field]) > 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def extract_free_slots(
    booking_date: str,
    slice_data: object,
) -> tuple[bool, list[dict[str, str]]]:
    places = _rows(slice_data, "placelist", "placeList")
    raw_slots = _rows(slice_data, "slicelist", "sliceList")
    if not places:
        if raw_slots:
            raise NswttProtocolError("NSWTT slots have no corresponding courts")
        return False, []
    place_names = {
        str(place.get("id") or place.get("placeid") or ""): str(
            place.get("placename") or place.get("name") or ""
        ).strip()
        for place in places
        if isinstance(place, dict)
    }
    slots: list[dict[str, str]] = []
    for raw_slot in raw_slots:
        if not isinstance(raw_slot, dict) or not _slice_is_free(raw_slot):
            continue
        court_name = place_names.get(str(raw_slot.get("placeid") or ""), "")
        start_time = str(raw_slot.get("starttime") or "").strip()
        end_time = str(raw_slot.get("endtime") or "").strip()
        if (
            not court_name
            or not TIME_PATTERN.fullmatch(start_time)
            or not TIME_PATTERN.fullmatch(end_time)
            or start_time >= end_time
        ):
            raise NswttProtocolError("NSWTT available slot has invalid court or times")
        slots.append(
            {
                "date": booking_date,
                "court_name": court_name,
                "start_time": start_time,
                "end_time": end_time,
            }
        )
    return True, slots


def _publish_unhealthy(error_name: str) -> None:
    publish_venue_observation(
        VENUE_ID,
        VENUE_NAME,
        [],
        healthy=False,
        error=error_name,
    )


def run_check_dashahe_free_courts() -> dict[str, object]:
    try:
        config_value = _load_config_value()
        config = NswttConfig.from_value(config_value)
        client = NswttClient(config)
        calendar = client.calendar_list()
        dates = ready_free_dates(calendar.get("data"))
        slots: list[dict[str, str]] = []
        free_dates: list[str] = []
        errors: list[str] = []
        for booking_date in dates:
            try:
                response = client.slice_list(booking_date)
                has_free_courts, date_slots = extract_free_slots(
                    booking_date,
                    response.get("data"),
                )
                if not has_free_courts:
                    print(f"[NSWTT] no free courts released for date={booking_date}")
                    continue
                free_dates.append(booking_date)
                slots.extend(date_slots)
            except Exception as exc:
                errors.append(f"{booking_date}: {type(exc).__name__}")
        slots = future_slots(slots)
        observation = publish_venue_observation(
            VENUE_ID,
            VENUE_NAME,
            slots,
            healthy=not errors,
            error="; ".join(errors) or None,
        )
        if errors:
            raise RuntimeError("one or more NSWTT free-date checks failed")
        # No WeChat preclaim until the email/observation authority durably ACKs.
        if observation.get("success") is not True:
            print("[NSWTT] notification pipeline degraded: observation_not_acknowledged")
            return {
                "ready_dates": dates,
                "free_dates": free_dates,
                "available_slot_count": len(slots),
                "observation_published": False,
                "wechat_queued": False,
            }
        cache = _load_cache()
        delivery: list[dict[str, Any]] = []
        pending_messages = [
            message for message in format_wechat_messages(slots) if message not in cache
        ]
        if pending_messages:
            cache.extend(pending_messages)
            _store_cache(cache)
            delivery = send_wechat_text_to_chatrooms_best_effort(
                list(WECHAT_CHATROOMS),
                "\n".join(pending_messages),
                source=DAG_ID,
                booking_venue_id=VENUE_ID,
            )
        print(
            f"[NSWTT] inspection complete ready_dates={len(dates)}, "
            f"free_dates={len(free_dates)}, available_slots={len(slots)}"
        )
        return {
            "ready_dates": dates,
            "free_dates": free_dates,
            "available_slot_count": len(slots),
            "observation_published": True,
            "wechat_queued": bool(delivery)
            and all(item.get("queued") is True for item in delivery),
            "wechat_enqueue_failed": any(item.get("success") is not True for item in delivery),
        }
    except Exception as exc:
        if (
            not isinstance(exc, RuntimeError)
            or str(exc) != "one or more NSWTT free-date checks failed"
        ):
            _publish_unhealthy(type(exc).__name__)
        raise
