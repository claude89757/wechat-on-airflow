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
from wechat_airflow.venues.dsh_ydmap_client import (
    CONFIG_VARIABLE,
    DEFAULT_DAYS,
    CourtAvailability,
    PiDeviceConfig,
    fetch_inspect_payload,
    parse_inspect_payload,
)

VENUE_ID = "dsh"
VENUE_NAME = "大沙河国际网球中心"
CACHE_KEY = "大沙河国际网球中心"
DAG_ID = "大沙河国际网球中心巡检"
LOOKAHEAD_DAYS = DEFAULT_DAYS
MAX_CACHED_MESSAGES = 100
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
FARTHEST_BOOKING_DATE_OPEN_TIME = datetime.time(12, 0)


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


def inspection_days_for(now: datetime.datetime) -> int:
    """Return the currently released booking horizon.

    The rolling fifth date is visible in the mini program before it becomes
    bookable, but its disabled cells must not be interpreted as availability.
    """
    if LOOKAHEAD_DAYS <= 1 or now.time() >= FARTHEST_BOOKING_DATE_OPEN_TIME:
        return LOOKAHEAD_DAYS
    return LOOKAHEAD_DAYS - 1


def merge_time_ranges(data: list[list[str]]) -> list[list[str]]:
    if not data:
        return data

    def time_to_minutes(time_str: str) -> int:
        return int(time_str[:2]) * 60 + int(time_str[3:])

    data_in_minutes = sorted((time_to_minutes(start), time_to_minutes(end)) for start, end in data)
    merged: list[tuple[int, int]] = []
    start, end = data_in_minutes[0]
    for next_start, next_end in data_in_minutes[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            merged.append((start, end))
            start, end = next_start, next_end
    merged.append((start, end))
    return [
        [f"{item[0] // 60:02d}:{item[0] % 60:02d}", f"{item[1] // 60:02d}:{item[1] % 60:02d}"]
        for item in merged
    ]


def parse_end_time_for_duration(end_time: str) -> datetime.datetime:
    if end_time == "24:00":
        return datetime.datetime.strptime("23:59", "%H:%M") + datetime.timedelta(minutes=1)
    return datetime.datetime.strptime(end_time, "%H:%M")


def parse_end_time_for_overlap(end_time: str) -> datetime.datetime:
    if end_time == "24:00":
        return datetime.datetime.strptime("22:00", "%H:%M")
    return datetime.datetime.strptime(end_time, "%H:%M")


def filter_court_data_for_notification(
    input_date: str, court_data: CourtAvailability
) -> list[NotificationCourt]:
    up_for_send_data_list: list[NotificationCourt] = []
    inform_date = datetime.datetime.strptime(input_date, "%Y-%m-%d").strftime("%m-%d")
    check_date = datetime.datetime.strptime(input_date, "%Y-%m-%d")
    is_weekend = check_date.weekday() >= 5
    if is_weekend:
        target_start = datetime.datetime.strptime("16:00", "%H:%M")
        target_end = datetime.datetime.strptime("22:00", "%H:%M")
    else:
        target_start = datetime.datetime.strptime("18:00", "%H:%M")
        target_end = datetime.datetime.strptime("22:00", "%H:%M")

    for court_name, free_slots in court_data.items():
        filtered_slots: list[list[str]] = []
        for slot in merge_time_ranges(free_slots):
            start_time = datetime.datetime.strptime(slot[0], "%H:%M")
            duration_minutes = (
                parse_end_time_for_duration(slot[1]) - start_time
            ).total_seconds() / 60
            if duration_minutes < 60:
                continue
            end_time_for_overlap = parse_end_time_for_overlap(slot[1])
            if max(start_time, target_start) < min(end_time_for_overlap, target_end):
                filtered_slots.append(slot)
        if filtered_slots:
            up_for_send_data_list.append(
                {
                    "date": inform_date,
                    "court_name": f"{VENUE_NAME}{court_name}",
                    "free_slot_list": filtered_slots,
                }
            )
    return up_for_send_data_list


def build_new_notifications(
    up_for_send_data_list: list[NotificationCourt],
    sended_msg_list: list[str],
    current_year: int | None = None,
) -> list[str]:
    if current_year is None:
        current_year = datetime.datetime.now().year
    up_for_send_msg_list: list[str] = []
    for data in up_for_send_data_list:
        date_obj = datetime.datetime.strptime(f"{current_year}-{data['date']}", "%Y-%m-%d")
        weekday_str = ["一", "二", "三", "四", "五", "六", "日"][date_obj.weekday()]
        for free_slot in data["free_slot_list"]:
            notification = (
                f"【{data['court_name']}】星期{weekday_str}({data['date']})空场: "
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
    if datetime.time(0, 0) <= now.time() < datetime.time(8, 0):
        print("每天0点-8点不巡检")
        publish_venue_observation(VENUE_ID, VENUE_NAME, [], healthy=True)
        return

    run_start_time = time.time()
    inspection_days = inspection_days_for(now)
    if inspection_days < LOOKAHEAD_DAYS:
        farthest_date = (now.date() + datetime.timedelta(days=LOOKAHEAD_DAYS - 1)).isoformat()
        print_with_timestamp(
            f"{farthest_date} 为最远可预订日期，12:00前尚未开放，本轮跳过该日期"
        )

    print_with_timestamp(f"start to check {VENUE_NAME}...")
    webapp_slots: list[dict[str, str]] = []
    up_for_send_data_list: list[NotificationCourt] = []
    try:
        payload = fetch_inspect_payload(_load_device_config(), days=inspection_days)
        availability = parse_inspect_payload(payload)
        for offset in range(inspection_days):
            input_date = (now.date() + datetime.timedelta(days=offset)).isoformat()
            court_data = availability.get(input_date, {})
            webapp_slots.extend(flatten_court_slots(input_date, court_data))
            print_court_data(input_date, court_data)
            up_for_send_data_list.extend(filter_court_data_for_notification(input_date, court_data))
        publish_venue_observation(VENUE_ID, VENUE_NAME, webapp_slots, healthy=True)
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
            current_year=now.year,
        )
        if up_for_send_msg_list:
            sended_msg_list.extend(up_for_send_msg_list)
            Variable.set(
                key=CACHE_KEY,
                value=sended_msg_list[-MAX_CACHED_MESSAGES:],
                description=(
                    f"{VENUE_NAME}网球场场地通知 - 最后更新: "
                    f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
                ),
                serialize_json=True,
            )
            enqueue_wechat_message("\n".join(up_for_send_msg_list))

    print_with_timestamp(f"Total cost time: {time.time() - run_start_time:.2f}s")
