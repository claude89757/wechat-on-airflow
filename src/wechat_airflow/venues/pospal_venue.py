"""Shared PosPal / 银豹 tennis appointment adapter."""

from __future__ import annotations

import datetime
import random
import time
from dataclasses import dataclass
from typing import TypedDict, cast

import requests
import urllib3
from airflow.sdk import Variable

from wechat_airflow.notifications.webapp import (
    flatten_court_slots,
    publish_venue_observation,
)
from wechat_airflow.notifications.wechat import send_wechat_text_to_chatrooms_best_effort

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

POSPAL_API_URL = (
    "https://wxservice-stg48.pospal.cn/wxapi/AppointmentVenue/LoadValidClassRoomApptSettingV2"
)
PROXY_LIST_URL = (
    "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt"
)
FSB_CHAIN_PROJECT_UID = "1768357901249380361"
FSB_PROXY_CACHE_KEY = "FSB_PROXY_CACHE"
LOOKAHEAD_DAYS = 3
MAX_CACHED_PROXIES = 10
MAX_CACHED_MESSAGES = 100
EXCLUDED_COURT_TOKENS = ("小场", "匹克", "练习")


class NotificationCourt(TypedDict):
    date: str
    court_name: str
    free_slot_list: list[list[str]]


CourtAvailability = dict[str, list[list[str]]]


@dataclass(frozen=True)
class PosPalVenue:
    venue_id: str
    venue_name: str
    store_id: str
    project_uid: str
    cache_key: str
    dag_id: str
    proxy_cache_key: str = FSB_PROXY_CACHE_KEY


FSB_SHENYUN = PosPalVenue(
    venue_id="fsb_shenyun",
    venue_name="泛思博特深云",
    store_id="6019572",
    project_uid=FSB_CHAIN_PROJECT_UID,
    cache_key="泛思博特深云网球场",
    dag_id="泛思博特深云网球场巡检",
)
FSB_SHEKOU = PosPalVenue(
    venue_id="fsb_shekou",
    venue_name="泛思博特蛇口",
    store_id="6019561",
    project_uid=FSB_CHAIN_PROJECT_UID,
    cache_key="泛思博特蛇口网球场",
    dag_id="泛思博特蛇口网球场巡检",
)
FSB_XINAN = PosPalVenue(
    venue_id="fsb_xinan",
    venue_name="泛思博特新安",
    store_id="6019579",
    project_uid=FSB_CHAIN_PROJECT_UID,
    cache_key="泛思博特新安网球场",
    dag_id="泛思博特新安网球场巡检",
)
FSB_ZHENGZHONG = PosPalVenue(
    venue_id="fsb_zhengzhong",
    venue_name="泛思博特正中",
    store_id="6019533",
    project_uid=FSB_CHAIN_PROJECT_UID,
    cache_key="泛思博特正中网球场",
    dag_id="泛思博特正中网球场巡检",
)
FSB_ATUOSHAN = PosPalVenue(
    venue_id="fsb_atuoshan",
    venue_name="泛思博特安托山",
    store_id="6019581",
    project_uid=FSB_CHAIN_PROJECT_UID,
    cache_key="泛思博特安托山网球场",
    dag_id="泛思博特安托山网球场巡检",
)

CHAIN_VENUES: dict[str, PosPalVenue] = {
    venue.venue_id: venue
    for venue in (FSB_SHENYUN, FSB_SHEKOU, FSB_XINAN, FSB_ZHENGZHONG, FSB_ATUOSHAN)
}


def print_with_timestamp(*args: object) -> None:
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args)


def _as_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def is_standard_tennis_court(court_name: str) -> bool:
    normalized = court_name.strip()
    if not normalized:
        return False
    return not any(token in normalized for token in EXCLUDED_COURT_TOKENS)


def normalize_time(time_str: str) -> str:
    if not time_str:
        return time_str
    parts = time_str.split(":")
    if len(parts) == 2:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return time_str


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


def parse_slot_time(begin_datetime: str, end_datetime: str) -> list[str]:
    begin_dt = datetime.datetime.strptime(begin_datetime, "%Y-%m-%d %H:%M:%S")
    end_dt = datetime.datetime.strptime(end_datetime, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(
        minutes=1
    )
    start_time = begin_dt.strftime("%H:%M")
    end_time = "24:00" if end_dt.date() > begin_dt.date() else end_dt.strftime("%H:%M")
    return [normalize_time(start_time), normalize_time(end_time)]


def parse_availability(json_data: object) -> CourtAvailability:
    payload = _as_mapping(json_data)
    result = _as_mapping(payload.get("result"))
    slots = result.get("slots")
    court_availability: dict[str, list[list[str]]] = {}
    if not isinstance(slots, list):
        return {}

    for raw_slot in slots:
        slot = _as_mapping(raw_slot)
        appt_info = _as_mapping(slot.get("apptInfo"))
        if appt_info.get("canApptOrNot") is not True:
            continue
        court_name = str(slot.get("classRoomName") or "未知场地")
        if not is_standard_tennis_court(court_name):
            print(f"skip non-standard court: {court_name}")
            continue
        begin_datetime = slot.get("beginDatetime")
        end_datetime = slot.get("endDatetime")
        if not isinstance(begin_datetime, str) or not isinstance(end_datetime, str):
            continue
        try:
            slot_time = parse_slot_time(begin_datetime, end_datetime)
        except Exception as error:
            print(f"解析时段失败: {court_name} {begin_datetime}-{end_datetime}, 错误: {error}")
            continue
        court_availability.setdefault(court_name, []).append(slot_time)

    return {
        court_name: merge_time_ranges(ranges) for court_name, ranges in court_availability.items()
    }


def parse_end_time_for_duration(end_time: str) -> datetime.datetime:
    if end_time == "24:00":
        return datetime.datetime.strptime("23:59", "%H:%M") + datetime.timedelta(minutes=1)
    return datetime.datetime.strptime(end_time, "%H:%M")


def parse_end_time_for_overlap(end_time: str) -> datetime.datetime:
    if end_time == "24:00":
        return datetime.datetime.strptime("22:00", "%H:%M")
    return datetime.datetime.strptime(end_time, "%H:%M")


def filter_court_data_for_notification(
    venue: PosPalVenue, input_date: str, court_data: CourtAvailability
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
        if not free_slots or not is_standard_tennis_court(court_name):
            continue
        filtered_slots: list[list[str]] = []
        for slot in free_slots:
            start_time = datetime.datetime.strptime(slot[0], "%H:%M")
            duration_minutes = (
                parse_end_time_for_duration(slot[1]) - start_time
            ).total_seconds() / 60
            if duration_minutes < 60:
                print(f"slot: {slot}, duration_minutes: {duration_minutes}, skip")
                continue
            end_time_for_overlap = parse_end_time_for_overlap(slot[1])
            if max(start_time, target_start) < min(end_time_for_overlap, target_end):
                filtered_slots.append(slot)
        if filtered_slots:
            up_for_send_data_list.append(
                {
                    "date": inform_date,
                    "court_name": f"{venue.venue_name}{court_name}",
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


def update_proxy_cache(proxy_cache_key: str, proxy: str, success: bool) -> list[str]:
    try:
        cached_proxies = _as_str_list(
            Variable.get(proxy_cache_key, deserialize_json=True, default=[])
        )
    except Exception:
        cached_proxies = []

    if success:
        if proxy not in cached_proxies:
            cached_proxies.insert(0, proxy)
            cached_proxies = cached_proxies[:MAX_CACHED_PROXIES]
            print(f"添加成功代理到缓存: {proxy}")
    elif proxy in cached_proxies:
        cached_proxies.remove(proxy)
        print(f"从缓存中移除失败代理: {proxy}")

    Variable.set(proxy_cache_key, cached_proxies, serialize_json=True)
    return cached_proxies


def get_tennis_court_availability(
    venue: PosPalVenue, date: str, proxy_list: list[str]
) -> CourtAvailability:
    got_response = False
    response: requests.Response | None = None
    successful_proxy: str | None = None
    try:
        cached_proxies = _as_str_list(
            Variable.get(venue.proxy_cache_key, deserialize_json=True, default=[])
        )
    except Exception:
        cached_proxies = []

    remaining_proxies = [proxy for proxy in proxy_list if proxy not in cached_proxies]
    random.shuffle(remaining_proxies)
    all_proxies_to_try = cached_proxies + remaining_proxies
    print(
        f"总共尝试代理数量: {len(all_proxies_to_try)} "
        f"(缓存: {len(cached_proxies)}, 其他: {len(remaining_proxies)})"
    )

    headers = {
        "STOREID": venue.store_id,
        "Content-Type": "application/json",
    }
    payload = {
        "dateTime": date,
        "projectUid": venue.project_uid,
    }

    for index, proxy in enumerate(all_proxies_to_try):
        print(f"尝试第 {index + 1} 个代理: {proxy}")
        try:
            candidate = requests.post(
                POSPAL_API_URL,
                headers=headers,
                json=payload,
                proxies={"https": proxy},
                verify=False,
                timeout=8,
            )
            if candidate.status_code != 200:
                print(f"代理失败: {proxy}, HTTP状态码: {candidate.status_code}")
                update_proxy_cache(venue.proxy_cache_key, proxy, False)
                continue
            json_data = cast(object, candidate.json())
            payload_data = _as_mapping(json_data)
            if payload_data.get("successed") is True and payload_data.get("status") == "success":
                result_data = _as_mapping(payload_data.get("result"))
                slots = result_data.get("slots")
                rooms = result_data.get("validClassRooms")
                print(
                    f"{venue.venue_name} API返回成功: "
                    f"slots={len(slots) if isinstance(slots, list) else 0}, "
                    f"rooms={len(rooms) if isinstance(rooms, list) else 0}"
                )
                got_response = True
                successful_proxy = proxy
                response = candidate
                time.sleep(1)
                break
            print(f"代理失败: {proxy}, API返回错误: {payload_data.get('status')}")
            update_proxy_cache(venue.proxy_cache_key, proxy, False)
        except Exception as error:
            print(f"代理异常: {proxy}, 错误: {error}")
            update_proxy_cache(venue.proxy_cache_key, proxy, False)

    if successful_proxy:
        update_proxy_cache(venue.proxy_cache_key, successful_proxy, True)
    if got_response and response is not None:
        return parse_availability(cast(object, response.json()))
    raise Exception("all proxies failed")


def load_proxy_list() -> list[str]:
    try:
        response = requests.get(PROXY_LIST_URL, timeout=10, verify=False)
        proxy_list = [line.strip() for line in response.text.strip().split("\n") if line.strip()]
        random.shuffle(proxy_list)
        print(f"Loaded {len(proxy_list)} proxies from {PROXY_LIST_URL}")
        return proxy_list
    except Exception as error:
        print(f"获取代理列表失败: {error}")
        return []


def print_court_data(input_date: str, court_data: CourtAvailability) -> None:
    print_with_timestamp(f"=== {input_date} 可预订场地详细信息 ===")
    if court_data:
        for court_name, free_slots in court_data.items():
            print_with_timestamp(f"【{court_name}】:")
            if free_slots:
                for slot in free_slots:
                    duration_minutes = (
                        parse_end_time_for_duration(slot[1])
                        - datetime.datetime.strptime(slot[0], "%H:%M")
                    ).total_seconds() / 60
                    print_with_timestamp(
                        f"  - {slot[0]}-{slot[1]} (时长: {int(duration_minutes)}分钟)"
                    )
            else:
                print_with_timestamp("  - 无可预订时间段")
    else:
        print_with_timestamp("无可预订场地数据")
    print_with_timestamp("=" * 50)


def enqueue_wechat_message(venue: PosPalVenue, all_in_one_msg: str) -> object:
    chat_names = Variable.get("SZ_TENNIS_CHATROOMS", default="")
    chat_names_list = str(chat_names).splitlines()
    print(f"chat_names_list: {chat_names_list}")
    return send_wechat_text_to_chatrooms_best_effort(
        chat_names_list,
        all_in_one_msg,
        source=venue.dag_id,
        booking_venue_id=venue.venue_id,
    )


def run_check(venue: PosPalVenue) -> None:
    if datetime.time(0, 0) <= datetime.datetime.now().time() < datetime.time(8, 0):
        print("每天0点-8点不巡检")
        publish_venue_observation(venue.venue_id, venue.venue_name, [], healthy=True)
        return

    run_start_time = time.time()
    print_with_timestamp(f"start to check {venue.venue_name}网球场...")
    proxy_list = load_proxy_list()
    up_for_send_data_list: list[NotificationCourt] = []
    webapp_slots: list[dict[str, str]] = []
    webapp_errors: list[str] = []
    for index in range(LOOKAHEAD_DAYS):
        input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime("%Y-%m-%d")
        print(f"checking {input_date}...")
        try:
            court_data = get_tennis_court_availability(venue, input_date, proxy_list)
            webapp_slots.extend(flatten_court_slots(input_date, court_data))
            print_court_data(input_date, court_data)
            time.sleep(1)
            up_for_send_data_list.extend(
                filter_court_data_for_notification(venue, input_date, court_data)
            )
        except Exception as error:
            print(f"Error checking date {input_date}: {error}")
            webapp_errors.append(str(error))

    publish_venue_observation(
        venue.venue_id,
        venue.venue_name,
        webapp_slots,
        healthy=not webapp_errors,
        error="; ".join(webapp_errors) or None,
    )

    if up_for_send_data_list:
        sended_msg_list = _as_str_list(
            Variable.get(venue.cache_key, deserialize_json=True, default=[])
        )
        up_for_send_msg_list = build_new_notifications(up_for_send_data_list, sended_msg_list)
        if up_for_send_msg_list:
            sended_msg_list.extend(up_for_send_msg_list)
            Variable.set(
                key=venue.cache_key,
                value=sended_msg_list[-MAX_CACHED_MESSAGES:],
                description=(
                    f"{venue.venue_name}网球场场地通知 - 最后更新: "
                    f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                ),
                serialize_json=True,
            )
            enqueue_wechat_message(venue, "\n".join(up_for_send_msg_list))

    print_with_timestamp(f"Total cost time: {time.time() - run_start_time:.2f}s")
