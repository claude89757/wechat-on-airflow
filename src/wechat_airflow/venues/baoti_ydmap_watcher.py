"""Bao'an Tennis Center availability inspection through the YDMap browser scrape."""

from __future__ import annotations

import datetime
import time
from typing import TypedDict
from zoneinfo import ZoneInfo

from airflow.sdk import Variable

from wechat_airflow.notifications.webapp import (
    flatten_court_slots,
    publish_venue_observation,
)
from wechat_airflow.notifications.wechat import send_wechat_text_to_chatrooms_best_effort
from wechat_airflow.venues.baoti_ydmap_client import (
    DEFAULT_DAYS,
    VENUE_ID,
    VENUE_NAME,
    fetch_inspect_payload,
    parse_inspect_payload,
)
from wechat_airflow.venues.dsh_ydmap_client import (
    CONFIG_VARIABLE,
    CourtAvailability,
    PiDeviceConfig,
)
from wechat_airflow.venues.ydmap_ranges import merge_time_ranges

DAG_ID = "宝安网球中心巡检"
CACHE_KEY = "宝安网球中心"
MAX_CACHED_MESSAGES = 400
MIN_NOTIFY_MINUTES = 60
QUIET_START = datetime.time(0, 0)
QUIET_END = datetime.time(8, 0)
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


class NotificationCourt(TypedDict):
    date: str
    court_name: str
    free_slot_list: list[list[str]]


def print_with_timestamp(*args: object) -> None:
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args)


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _load_device_config() -> PiDeviceConfig:
    return PiDeviceConfig.from_value(Variable.get(CONFIG_VARIABLE, deserialize_json=True))


def _local_now() -> datetime.datetime:
    return datetime.datetime.now(LOCAL_TIMEZONE)


def canonicalize_court_availability(court_data: CourtAvailability) -> CourtAvailability:
    """Collapse the scraper's half-hour cells into stable maximal ranges."""

    canonical: CourtAvailability = {}
    for court_name, free_slots in court_data.items():
        merged = merge_time_ranges(free_slots)
        if merged:
            canonical[court_name] = merged
    return canonical


def _duration_minutes(slot: list[str]) -> int:
    start_hour, start_minute = (int(part) for part in slot[0].split(":"))
    end_hour, end_minute = (int(part) for part in slot[1].split(":"))
    return (end_hour * 60 + end_minute) - (start_hour * 60 + start_minute)


def filter_court_data_for_notification(
    input_date: str, court_data: CourtAvailability
) -> list[NotificationCourt]:
    """Keep ranges long enough to be worth a booking reminder."""

    up_for_send_data_list: list[NotificationCourt] = []
    booking_date = datetime.datetime.strptime(input_date, "%Y-%m-%d").date().isoformat()
    for court_name, free_slots in court_data.items():
        filtered_slots = [
            slot
            for slot in merge_time_ranges(free_slots)
            if _duration_minutes(slot) >= MIN_NOTIFY_MINUTES
        ]
        if filtered_slots:
            up_for_send_data_list.append(
                {
                    "date": booking_date,
                    "court_name": f"{VENUE_NAME}·{court_name}",
                    "free_slot_list": filtered_slots,
                }
            )
    return up_for_send_data_list


def build_new_notifications(
    up_for_send_data_list: list[NotificationCourt],
    sended_msg_list: list[str],
) -> list[str]:
    up_for_send_msg_list: list[str] = []
    for data in up_for_send_data_list:
        date_obj = datetime.datetime.strptime(data["date"], "%Y-%m-%d")
        weekday_str = ["一", "二", "三", "四", "五", "六", "日"][date_obj.weekday()]
        for free_slot in data["free_slot_list"]:
            notification = (
                f"【{data['court_name']}】星期{weekday_str}({date_obj.strftime('%m-%d')})空场: "
                f"{free_slot[0]}-{free_slot[1]}"
            )
            if notification not in sended_msg_list:
                up_for_send_msg_list.append(notification)
    return up_for_send_msg_list


def enqueue_wechat_message(all_in_one_msg: str) -> object:
    chat_names = Variable.get("SZ_TENNIS_CHATROOMS", default="")
    chat_names_list = str(chat_names).splitlines()
    return send_wechat_text_to_chatrooms_best_effort(
        chat_names_list,
        all_in_one_msg,
        source=DAG_ID,
        booking_venue_id=VENUE_ID,
    )


def print_court_data(input_date: str, court_data: CourtAvailability) -> None:
    print_with_timestamp(f"=== {input_date} 可预订场地 ===")
    if not court_data:
        print_with_timestamp("无可预订场地数据")
        return
    for court_name, free_slots in court_data.items():
        print_with_timestamp(f"【{court_name}】 {free_slots}")


def run_check_tennis_courts() -> None:
    now = _local_now()
    if QUIET_START <= now.time() < QUIET_END:
        print("每天0点-8点不巡检")
        publish_venue_observation(VENUE_ID, VENUE_NAME, [], healthy=True)
        return

    run_start_time = time.time()
    print_with_timestamp(f"start to check {VENUE_NAME}...")
    webapp_slots: list[dict[str, str]] = []
    up_for_send_data_list: list[NotificationCourt] = []
    try:
        payload = fetch_inspect_payload(_load_device_config(), days=DEFAULT_DAYS)
        expected_dates = {
            (now.date() + datetime.timedelta(days=offset)).isoformat()
            for offset in range(DEFAULT_DAYS)
        }
        availability = parse_inspect_payload(payload, expected_dates=expected_dates)
        for input_date in sorted(availability):
            court_data = canonicalize_court_availability(availability.get(input_date, {}))
            webapp_slots.extend(flatten_court_slots(input_date, court_data))
            print_court_data(input_date, court_data)
            up_for_send_data_list.extend(filter_court_data_for_notification(input_date, court_data))
        observation = publish_venue_observation(VENUE_ID, VENUE_NAME, webapp_slots, healthy=True)
        if observation.get("success") is not True:
            print_with_timestamp("Observation was not acknowledged; skipping WeChat enqueue")
            return
    except Exception as error:
        print(f"Error checking {VENUE_NAME}: {error}")
        publish_venue_observation(
            VENUE_ID,
            VENUE_NAME,
            webapp_slots,
            healthy=False,
            error=type(error).__name__,
        )
        print_with_timestamp(f"Total cost time: {time.time() - run_start_time:.2f}s")
        return

    if up_for_send_data_list:
        sended_msg_list = _as_str_list(Variable.get(CACHE_KEY, deserialize_json=True, default=[]))
        up_for_send_msg_list = build_new_notifications(
            up_for_send_data_list,
            sended_msg_list,
        )
        if up_for_send_msg_list:
            sended_msg_list.extend(up_for_send_msg_list)
            Variable.set(
                key=CACHE_KEY,
                value=sended_msg_list[-MAX_CACHED_MESSAGES:],
                description=(
                    f"{VENUE_NAME}网球场场地通知 - 最后更新: {now.strftime('%Y-%m-%d %H:%M:%S')}"
                ),
                serialize_json=True,
            )
            enqueue_wechat_message("\n".join(up_for_send_msg_list))

    print_with_timestamp(f"Total cost time: {time.time() - run_start_time:.2f}s")
